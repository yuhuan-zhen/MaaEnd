"""日常编排：按 MXU 预设顺序跑任务，逐项记录结果。

复现 MXU 的「预设 → 任务列表 → 选项覆盖」行为：预设解析在 :mod:`maaend_web.preset`，
选择语义在 :mod:`maaend_web.plan`，这里只做编排（选任务 → 起资源/控制器/agent → 跑 → 汇总）。

用法::

    python3 run_daily_linux.py --only 1,2,3          # 试点
    python3 run_daily_linux.py                       # 全量
    python3 run_daily_linux.py --from 5 --to 9
    python3 run_daily_linux.py --instance <预设 id> --dry-run

退出码：0 = 全部成功；3 = 资源加载失败；4 = 控制器连不上；7 = 有任务失败/超时。
（其余异常走 Python 默认的 rc=1；预设里找不到实例时抛 SystemExit 文案，rc=1。）
"""

import argparse
import contextlib
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from maaend_web.framework import (
    CONTROLLER_CDP,
    CONTROLLER_KINDS,
    CONTROLLER_WLROOTS,
    ControlUnitLoadError,
    ensure_relative_move_support,
    make_controller,
    probe_relative_move,
    setup_tasker,
    start_agents,
    stop_agents,
)
from maaend_web.recovery import START_CAP, START_NODE, Recoverer

# web/linux：资源覆盖层与 reset_page.py 都在这一层（cli/daily.py 往上三级）
LINUX_DIR = Path(__file__).resolve().parents[2]

EXIT_OK = 0
EXIT_RESOURCE = 3
EXIT_CONTROLLER = 4
EXIT_TASK_FAILED = 7


def log(msg: str) -> None:
    """带时间戳的 stdout 日志（cron 里重定向到 daily.log，时间戳是唯一的时间线索）。"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    """命令行参数：生产版与上游重构版的并集，只增不减（PLAN.md 第 5 节）。"""
    ap = argparse.ArgumentParser(
        prog="run_daily_linux.py",
        description="按 MXU 预设顺序跑云·终末地网页端日常任务",
    )
    ap.add_argument("--only", default="", help="按序号挑任务，如 1,2,3")
    ap.add_argument("--tasks", default="", help="按名字或序号挑任务，支持 1-5 / WebStartGame,VisitFriends")
    ap.add_argument("--from", dest="frm", type=int, default=1)
    ap.add_argument("--to", dest="to", type=int, default=99)
    ap.add_argument(
        "--instance",
        default=os.environ.get("MAAEND_INSTANCE", ""),
        help="预设实例 id（默认取 MAAEND_INSTANCE，都没有时用 mxu-MaaEnd.json 里的第一个实例）",
    )
    ap.add_argument("--skip-in-game-check", action="store_true")
    ap.add_argument(
        "--attempts",
        type=int,
        default=2,
        help="每个任务的最多尝试次数（含首次），默认 2；外层已有重试链时可传 1 避免叠加",
    )
    ap.add_argument("--no-agent", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只打印要跑的任务，不连控制器")
    ap.add_argument(
        "--controller",
        default=os.environ.get("MAAEND_CONTROLLER", CONTROLLER_WLROOTS),
        choices=list(CONTROLLER_KINDS),
        help="wlroots=合成器截图（默认，homesrv 生产路径）；cdp=云串流原生帧（更锐利，需浏览器 CDP）",
    )
    ap.add_argument(
        "--no-overlay",
        action="store_true",
        help="兼容性验证：只加载上游原版资源，不加载我们的覆盖层",
    )
    # 两个开关共用 dest：--no-state-machine 是生产/上游都有的写法，--state-machine 只是显式回到默认
    ap.add_argument(
        "--state-machine",
        dest="state_machine",
        action="store_true",
        default=argparse.SUPPRESS,
        help="用页面状态机启动（默认即为开）",
    )
    ap.add_argument(
        "--no-state-machine",
        dest="state_machine",
        action="store_false",
        default=argparse.SUPPRESS,
        help="不用页面状态机启动，退回 pipeline 启动链",
    )
    ap.set_defaults(state_machine=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    """日常编排入口：解析参数 -> 选任务 -> 起资源/控制器/agent -> 跑 -> 汇总。"""
    args = build_parser().parse_args(argv)

    # 只有 wlroots 才需要控制单元的 relative_move / scroll：cdp 走 <video> 原生帧
    # 加 CDP 输入，根本不加载 LinuxController（见 framework.make_controller 的分支）。
    # 无条件预加载会把调试对照路径也挡在 DSO 的系统依赖之外——缺 libei/pipewire 的机器
    # 上连「只想用 cdp 看看」都跑不起来。放在 parse_args 之后，是为了 --help 不 import maa。
    if args.controller == CONTROLLER_WLROOTS:
        try:
            ensure_relative_move_support(log)
        except ControlUnitLoadError as e:
            # 装坏了：立刻停，不要跑到一半才发现转不了视角
            raise SystemExit(str(e)) from None

    try:
        inst, plan = _select(args)
    except LookupError as e:
        # 预设里没有这个实例：转成旧版的 SystemExit 文案（rc=1、不带 traceback）
        raise SystemExit(str(e)) from None
    log(f"待跑 {len(plan)} 项: {'/'.join(p.name for p in plan)}")
    if args.dry_run:
        for i, p in enumerate(plan, 1):
            log(f"  {i:2d}. {p.name:<22} -> {p.entry:<32} 覆盖 {p.n_override} 项")
        return EXIT_OK

    from maa.resource import Resource
    from maa.tasker import Tasker

    from maaend_web.config import load_settings

    settings = load_settings()
    res = _post_bundles(Resource(), _resource_dirs(args, settings))
    if not res.loaded:
        log("[X] 资源加载失败，任务不可能跑对，直接退出")
        return EXIT_RESOURCE

    ctrl = _connect_controller(args.controller, settings)
    if ctrl is None:
        return EXIT_CONTROLLER
    # 合成器截图模式下也要能问页面「现在在哪一态」：帧走合成器，状态机/注入/
    # 页面内点击走 CDP。拿不到就退化到 pipeline 启动链（实测会卡在落地页不点「开始游戏」）。
    page_ctl = _page_control(settings) if args.controller != CONTROLLER_CDP else None

    tasker = Tasker()
    tasker.bind(res, ctrl)
    setup_tasker(tasker, settings, log)

    agents: list[tuple[Any, Any]] = []
    try:
        if not args.no_agent:
            log("== 启动 agents（go-service + cpp-algo）==")
            agents = start_agents(res, settings, resource_name=_resource_name(inst), log=log)
            if not any(client is not None for client, _proc in agents):
                log("  ! 没有 agent，自定义动作的任务会失败")

        rec = Recoverer(tasker, ctrl, settings, log)
        if plan and plan[0].name != "WebStartGame" and not args.skip_in_game_check:
            _ensure_in_game_once(args, ctrl, page_ctl, rec)
        writer = _writer(settings)
        return _summary(writer, _run_plan(args, plan, tasker, rec, writer))
    finally:
        stop_agents(agents, log)


# ---------------------------------------------------------------------- 选任务
def _select(args: argparse.Namespace) -> tuple[dict[str, Any], list[Any]]:
    """读预设 + 按 ``--tasks``/``--only``/``--from-to`` 选任务。

    「有没有 entry / 是否启用」的过滤在 ``select_plan`` 内部完成（与重构前同一条规则）；
    「序号越界 / 未知任务」的提示按旧日志原文加 ``[X]`` 前缀打印，保证 --dry-run 可逐字对比。
    """
    from maaend_web.plan import select_plan_with_notes
    from maaend_web.preset import load_preset

    inst, plan = load_preset(args.instance)
    picked, notes = select_plan_with_notes(plan, tasks=args.tasks, only=args.only, frm=args.frm, to=args.to)
    for note in notes:
        log(f"[X] {note}")
    return inst, picked


def _resource_name(inst: dict[str, Any]) -> str:
    """实例里声明的资源名（agent 的 PI_RESOURCE 要用），取不到就用发行版默认名。"""
    name = inst.get("resourceName")
    return str(name) if name else "官服-网页端"


# ---------------------------------------------------------------------- 资源
def _resource_dirs(args: argparse.Namespace, settings: Any) -> list[Path]:
    """要加载的资源目录：预设目录 + （可选）CDP 专用覆盖层。"""
    dirs = list(settings.resource_dirs)
    if args.no_overlay:
        # 兼容性验证模式：只加载上游原版资源，不加载我们任何覆盖层。
        # 如果这样也能跑完，就说明「别人写的节点可以直接用」，覆盖层可以继续删。
        dirs = dirs[:1]
        log(f"[兼容性] --no-overlay：只加载 {dirs[0] if dirs else '(无资源目录)'}（不加载覆盖层）")
    if args.controller == CONTROLLER_CDP:
        # CDP 路径的模板要单独一层：无视频时走 Page.captureScreenshot，渲染与合成器帧
        # 有细微差异，灰度匹配分数会掉到 0.90~0.92（阈值 0.95）。
        layer = LINUX_DIR / "resource_web_cdp"
        if layer.is_dir():
            dirs.append(layer)
    return dirs


def _post_bundles(res: Any, dirs: Sequence[Path]) -> Any:
    """逐个 post_bundle 并等加载完；缺目录只告警不中断（覆盖层缺了还能用上游资源跑）。"""
    for d in [d for d in dirs if not d.is_dir()]:
        log(f"  ! 资源目录不存在，已跳过: {d}")
    for d in [d for d in dirs if d.is_dir()]:
        res.post_bundle(str(d)).wait()
    log(f"资源加载: {res.loaded}")
    return res


# ---------------------------------------------------------------------- 控制器
def _is_connected(ctrl: Any) -> bool:
    """CustomController 把 connected 写成方法，LinuxController 是属性，两种都要认。"""
    value = getattr(ctrl, "connected", False)
    return bool(value() if callable(value) else value)


def _connect_controller(kind: str, settings: Any) -> Any:
    """连控制器；cdp 不可用时降级到 wlroots，并在日志里显式标注（不静默降级）。"""
    ctrl = None
    if kind == CONTROLLER_CDP:
        try:
            ctrl = make_controller(CONTROLLER_CDP, settings, log)
        except Exception as e:
            # cdp 的依赖（numpy/pillow/websocket-client）由 maa 运行环境提供，缺了不该整批任务崩掉
            log(f"[!] 控制器 cdp 创建失败: {str(e)[:80]}")
    else:
        ctrl = make_controller(kind, settings, log)

    if ctrl is not None:
        ctrl.post_connection().wait()
        conn = _is_connected(ctrl)
        log(f"控制器: {kind} connected={conn}")
        if conn:
            if kind == CONTROLLER_WLROOTS:
                # 转视角能力自检：失败只告警不阻断 —— 不需要 relative_move 的任务照跑，
                # 需要时（地图导航）日志里早有明确根因，而不是等到任务跑一半才看到
                # 「Relative move is not supported」。
                try:
                    probe_relative_move(ctrl, log)
                    log("  relative_move 自检通过")
                except ControlUnitLoadError as e:
                    log(f"[!] {e}")
            return ctrl
        if kind != CONTROLLER_CDP:
            return None
        # CDP 连不上（浏览器没起来 / 端口没开）不能让整批任务白跑
        log("[!] CDP 控制器连接失败，回退到 wlroots（合成器截图）")

    ctrl = make_controller(CONTROLLER_WLROOTS, settings, log)
    ctrl.post_connection().wait()
    conn = _is_connected(ctrl)
    log(f"控制器: wlroots(回退) connected={conn}")
    return ctrl if conn else None


def _page_control(settings: Any) -> Any:
    """页面控制层（有 CDP 才有）：拿不到返回 None，启动链回退 pipeline。"""
    try:
        from maaend_web.page_control import PageControl

        page_ctl = PageControl(port=settings.cdp_port)
        if page_ctl.connect():
            log("页面控制层: CDP 已连上（状态机可用，帧仍走合成器）")
            return page_ctl
        log(f"[!] 页面控制层连不上 CDP（端口 {settings.cdp_port}），启动链只能回退 pipeline")
    except Exception as e:
        log(f"[!] 页面控制层初始化失败: {str(e)[:80]}")
    return None


# ---------------------------------------------------------------------- 启动
def _ensure_in_game_once(args: argparse.Namespace, ctrl: Any, page_ctl: Any, rec: Recoverer) -> bool:
    """开跑前把页面推进游戏：优先页面状态机，失败再回退 pipeline 启动链。

    状态机（page.prepare）直接读页面九态、点开始/确认，能当场告出「现在到底卡在
    哪一态」；pipeline 那 9 个启动链节点仍保留作兜底（尤其会话中途结束、页面掉回
    落地页时）。
    """
    page_driver = page_ctl if page_ctl is not None else ctrl
    if args.state_machine and hasattr(page_driver, "prepare_page"):
        log("  [启动] 页面状态机：等页面进入串流")
        try:
            if page_driver.prepare_page(timeout=90, log=log):
                log("    状态机已确认进入串流，跳过 pipeline 启动链")
                return True
        except Exception as e:
            log(f"    (状态机异常: {str(e)[:80]})")
        log("  ! 状态机没走通，回退到 pipeline 启动链")
    log("  [启动] 先跑 WebStartGameEntry（已在游戏内会自动跳过）")
    ok = rec.run_node(START_NODE, cap=START_CAP)
    log(f"    WebStartGameEntry -> {ok}")
    if not ok:
        log("  ! 启动失败，硬重置一次再试")
        ok = rec.hard_reset("[启动]")
        log(f"    硬重置后 WebStartGameEntry -> {ok}")
    return ok


# ---------------------------------------------------------------------- 跑任务
def _writer(settings: Any) -> Any:
    """结果落盘器：<probe_out>/daily_linux_progress.jsonl（与重构前同一个文件）。"""
    from maaend_web.results import ResultWriter

    return ResultWriter(Path(settings.probe_out) / "daily_linux_progress.jsonl")


def _run_one(tasker: Any, item: Any, attempt: int) -> Any:
    """提交一个任务并等到 done 或逐项超时上限，返回 results.TaskResult。"""
    from maaend_web.config import DEFAULT_TIMEOUT, TASK_TIMEOUTS
    from maaend_web.results import TaskResult

    t0 = time.time()
    job = tasker.post_task(item.entry, item.override)
    cap = TASK_TIMEOUTS.get(item.name, DEFAULT_TIMEOUT)
    while not job.done and time.time() - t0 < cap:
        time.sleep(1)
    dur = time.time() - t0
    if not job.done:
        with contextlib.suppress(Exception):
            # 超时必须停：框架同一时刻只跑一个 task，不停会把下一个任务卡在 pending
            tasker.post_stop().wait()
    return TaskResult(
        name=item.name,
        entry=item.entry,
        done=bool(job.done),
        succeeded=bool(job.succeeded),
        seconds=round(dur, 1),
        # 死字段：MaaFw 的 Job 不暴露「最后执行到哪个节点」，保留键以兼容历史 jsonl 读取方
        last_node=None,
        timeout=not job.done,
        attempt=attempt,
    )


def _run_plan(
    args: argparse.Namespace,
    plan: Sequence[Any],
    tasker: Any,
    rec: Recoverer,
    writer: Any,
) -> list[Any]:
    """逐项跑：前置恢复 -> 逐次尝试（失败留现场帧并恢复）-> 落盘。"""
    results: list[Any] = []
    for i, item in enumerate(plan, 1):
        name = item.name
        if not args.skip_in_game_check and name != "WebStartGame" and rec.needs_start():
            # 反向判据：只有看到启动按钮/标题页提示才算「没进游戏」（见 Recoverer.needs_start）
            log("  ! 当前不在游戏内，先跑 WebStartGame 恢复")
            log(f"    WebStartGameEntry: succeeded={rec.run_node(START_NODE, cap=START_CAP)}")
        if name != "WebStartGame" and not rec.in_world():
            rec.recover("[前置]")

        attempts = 1 if name == "WebStartGame" else max(1, args.attempts)
        st: Any = None
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                log(f"  ! {name} 重试第 {attempt} 次（先恢复）")
                rec.recover("[重试前]")
            retry = "" if attempt == 1 else " [重试]"
            log(f"--- ({i}/{len(plan)}) {name} -> {item.entry}  覆盖 {item.n_override} 项{retry}")
            st = _run_one(tasker, item, attempt)
            log(f"    => done={st.done} succeeded={st.succeeded} {st.seconds:.1f}s  last_node={st.last_node}")
            if st.succeeded:
                break
            rec.save_failshot(f"{name}-att{attempt}")
            if attempt < attempts:
                rec.recover("[失败后]")
        if st is not None:
            writer.write(st)
            results.append(st)
    return results


def _summary(writer: Any, results: Sequence[Any]) -> int:
    """汇总表 + 退出码：全成功 0，否则 7（外层脚本靠 rc 判成败）。"""
    for line in writer.summary(results).splitlines():
        log(line)
    ok = sum(1 for r in results if r.succeeded)
    return EXIT_OK if ok == len(results) else EXIT_TASK_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
