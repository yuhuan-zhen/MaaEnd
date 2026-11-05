"""runtime 框架层：LD_PRELOAD、Linux 控制器选择、agent 生命周期、tasker 配置。

这一层是唯一碰 `maa` 的 runtime 模块，而且所有 `maa` 导入都写在函数体内：
`--help` / `--dry-run` / 单元测试因此不需要安装框架。

取帧与输入注入是框架 C++ 的职责（``source/MaaLinuxControlUnit``），这里只做选择与装配；
``cdp`` 只是调试对照路径，实现在 ``web/linux/devtools/cdp.py``（非生产）。

用法::

    ensure_preload(log)                      # 需要 relative_move/scroll 时给自己 exec 一次
    ctrl = make_controller("wlroots", settings, log)
    agents = start_agents(res, settings, log=log)
"""

import contextlib
import ctypes
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from maaend_web.config import Settings

Log = Callable[[str], None]

# 控制单元 DSO 名：新框架（含 scroll / relative_move 的版本）用 boost::dll 加载它。
PRELOAD_SO = "libMaaLinuxControlUnit.so"

# ensure_relative_move_support 是否已跑过（幂等闸门）
_control_unit_ready = False

# RTLD_* 只在 POSIX 上存在；Windows 既没有这两个常量，也不会走到这条路径
# （ensure_relative_move_support 先判 sys.platform），取 0 只为避免导入期 AttributeError。
_RTLD_GLOBAL = getattr(ctypes, "RTLD_GLOBAL", 0)
_RTLD_FLAGS = _RTLD_GLOBAL | getattr(ctypes, "RTLD_NOW", 0)


class ControlUnitLoadError(RuntimeError):
    """控制单元 DSO 不可用 —— relative_move / scroll 必然失败。"""


CONTROLLER_WLROOTS = "wlroots"
CONTROLLER_CDP = "cdp"
CONTROLLER_KINDS = (CONTROLLER_WLROOTS, CONTROLLER_CDP)

# agent 目录里的固定同伴：与 go-service 同级，注册地图类识别与走位动作
CPP_ALGO = "cpp-algo"


def _control_unit_so() -> Path | None:
    """``bin/libMaaLinuxControlUnit.so`` 的绝对路径。

    三种情况必须分开，不能混成一个 None：

    * 没装 maa（``--help`` / ``--dry-run`` / 离线单测）→ ``None``，调用方跳过
    * 装了 maa 但没有这个 DSO → 抛 :class:`ControlUnitLoadError`（装坏了，不能装没事）
    * 正常 → 返回路径
    """
    try:
        import maa
    except Exception:  # 没有框架的机器：--help/--dry-run 照常走
        return None

    if sys.platform != "linux":  # 这个 DSO 只在 Linux 发行包里存在
        return None

    so = Path(os.path.dirname(getattr(maa, "__file__", "") or "")) / "bin" / PRELOAD_SO
    if not so.is_file():
        raise ControlUnitLoadError(
            f"{so} 不存在：relative_move/scroll 会全部失败"
            f"（日志表现为 'Relative move is not supported for this controller type'）。"
            f"检查 maa 安装是否完整（bin 目录应有 MaaLinuxControlUnit 相关 DSO）。"
        )
    return so


def ensure_relative_move_support(log: Log = print) -> None:
    """把控制单元 DSO 以 RTLD_GLOBAL 预加载进本进程，只对 Linux 有意义。

    为什么需要：MaaFramework 的 Linux 包用 libc++ 编译，``RelativeMovableUnit`` /
    ``ScrollableUnit`` 这类能力 mixin 的 typeinfo 在框架和控制单元两个 DSO 里各存一份，
    跨库 ``dynamic_cast`` 按地址比较因而失败，``relative_move`` / ``scroll`` 会被判成
    「不支持」。先把控制单元以 GLOBAL 加载，全局就只剩一份 typeinfo，cast 能过。

    何时调用：第一次构造 ``LinuxController`` 之前。**不必早于 ``import maa``** ——
    glibc 会把已 LOCAL 加载的库提升为 GLOBAL。

    幂等；成功与「不适用」都只记一行日志，真正的失败抛 :class:`ControlUnitLoadError`。
    """
    global _control_unit_ready
    if _control_unit_ready:
        return

    if sys.platform != "linux":
        _control_unit_ready = True
        return

    if PRELOAD_SO in os.environ.get("LD_PRELOAD", ""):
        _control_unit_ready = True
        log(f"  {PRELOAD_SO} 已由 LD_PRELOAD 加载，跳过预加载")
        return

    so = _control_unit_so()
    if so is None:
        _control_unit_ready = True
        return

    try:
        ctypes.CDLL(str(so), mode=_RTLD_FLAGS)
    except OSError as exc:
        raise ControlUnitLoadError(f"无法以 RTLD_GLOBAL 加载 {so}: {exc}") from exc

    _control_unit_ready = True
    log(f"  已把 {so.name} 载入全局符号（relative_move/scroll 依赖）")


def ensure_preload(log: Log = print) -> None:
    """已废弃：现在不重新 exec 自己，改用进程内 RTLD_GLOBAL。保留旧名给外部脚本。"""
    ensure_relative_move_support(log)


def probe_relative_move(ctrl: Any, log: Log = print) -> None:
    """控制器连上后自检一次 ``relative_move(0, 0)``。

    失败说明能力链断了（typeinfo 分裂 / input_method=None / DSO 没加载），
    现在报错远好过任务跑到转视角才发现。``(0, 0)`` 在 Wlr 下就是一次无位移的
    指针移动，无副作用。
    """
    try:
        import maa  # noqa: F401  仅用于判断「框架在不在」
    except Exception:  # 没有框架：无事可做
        return

    job = ctrl.post_relative_move(0, 0)
    if job.wait().status.succeeded:
        return

    raise ControlUnitLoadError(
        "relative_move 不可用（post_relative_move 失败）。依次检查："
        "(1) libMaaLinuxControlUnit.so 是否以 RTLD_GLOBAL 加载；"
        "(2) input_method 是否为 1/3/4（NoneInput 不支持）；"
        "(3) 日志里是否出现 'Relative move is not supported for this controller type'。"
    )


def find_wlr_socket(env: Mapping[str, str] | None = None) -> str:
    """wlroots 合成器的 wayland socket 路径（按 PLAN 契约从 framework 暴露）。

    真正的探测逻辑（``WLR_SOCKET`` -> ``XDG_RUNTIME_DIR``/wayland-1 -> 固定兜底路径）
    在 :mod:`maaend_web.config` 里，那里是环境变量与默认值的单一真源；这里只做转发，
    免得两处实现漂移。
    """
    from maaend_web.config import find_wlr_socket as _find_wlr_socket

    return _find_wlr_socket(env)


def make_controller(kind: str, settings: Settings, log: Log = print) -> Any:
    """按种类造控制器：wlroots=合成器截图（LinuxController，失败回落 WlRootsController）。

    wlroots 优先用新的 LinuxController：只有它背后的 LinuxControlUnitMgr 实现
    relative_move / scroll（转视角、滚轮）；废弃的 WlRootsController 走兼容层，
    这两个能力一律返回 "not supported"。
    cdp 是调试对照路径（``devtools/cdp.py``）：<video> 原生帧比合成器截图少两次重采样，
    锐度高；输入也走 CDP 注入，不依赖 sway。生产默认不走它。
    """
    if kind == CONTROLLER_CDP:
        from devtools.cdp import make_custom_controller

        return make_custom_controller(port=settings.cdp_port)

    from maa.controller import LinuxController, WlRootsController

    sock = settings.wlr_socket
    try:
        return LinuxController(
            {
                "screencap_method": 1,  # MaaLinuxScreencapMethod_Wlr
                "input_method": 1,  # MaaLinuxInputMethod_Wlr
                "wlr_socket_path": sock,
                # 管线的动作节点用的是 Win32 虚拟键码（Alt=18），不加这个参数，
                # 18 会被当成 Linux 键码（=E）。
                "use_win32_vk_code": True,
            }
        )
    except Exception as e:  # LinuxController 可能因 socket 不存在直接抛 RuntimeError
        log(f"  (LinuxController 创建失败，回落 WlRootsController: {str(e)[:80]})")
        return WlRootsController(sock, use_win32_vk_code=True)


def start_agent(
    res: Any,
    settings: Settings,
    *,
    bin_path: Path | None = None,
    tag: str | None = None,
    controller_name: str = "Linux-Wlroots",
    resource_name: str = "官服-网页端",
    log: Log = print,
) -> tuple[Any, subprocess.Popen | None]:
    """拉起单个 agent 并把它的自定义动作/识别绑到资源上，返回 (client, proc)。

    MaaEnd 的 SubTask / RepeatUntilFoundAction 等动作由 go-service 注册；cpp-algo
    注册 MapFind / MapLocateAssertLocation / MapNavigateAction 等地图类识别与
    走位动作。两者缺一，任务都会失败。
    """
    exe = Path(bin_path) if bin_path is not None else Path(settings.agent_bin)
    tag = tag or exe.name
    agent_dir = exe.parent
    if not exe.exists():
        # 先查路径再 import maa：配错 agent 路径时不该报「没有 MaaFramework」。
        log(f"  [X] 找不到 agent: {exe}")
        return None, None

    from maa.agent_client import AgentClient

    client = AgentClient.create_tcp(0)
    ident = client.identifier
    # 顺序很关键：必须先 bind(resource) 再 connect()，否则 connect 直接返回 False
    # （框架日志：AgentClient::connect() "resource is not bound"）
    log(f"  agent bind={client.bind(res)} (identifier={ident})")
    env = os.environ.copy()
    env.update(_pi_env(settings, controller_name, resource_name))
    agent_dir.mkdir(parents=True, exist_ok=True)
    # 日志落 agent 目录（go-service.log / cpp-algo.log）：与进程同一个 cwd，
    # 崩溃时框架和 agent 的输出在同一边，不用去别处找。
    # 用 with 只管父进程这一份句柄：Popen 时子进程已经拿到自己的 fd，关掉不影响它继续写。
    with open(agent_dir / (tag + ".log"), "ab", buffering=0) as logf:
        lib = str(settings.agent_lib)
        env["LD_LIBRARY_PATH"] = lib + ((":" + env["LD_LIBRARY_PATH"]) if env.get("LD_LIBRARY_PATH") else "")
        proc = subprocess.Popen(
            [str(exe), str(ident)],
            env=env,
            cwd=str(agent_dir),
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    ok = client.connect()
    log(f"  agent[{tag}] connect={ok} alive={client.alive} pid={proc.pid}")
    if not ok:
        return client, proc
    try:
        acts = list(client.custom_action_list)
        recs = list(client.custom_recognition_list)
        log(f"  自定义动作 {len(acts)} 个 / 识别 {len(recs)} 个")
        log(f"    动作样本: {', '.join(sorted(acts)[:8])}")
    except Exception as e:  # 列表接口取不到只影响这行日志，不影响任务本身
        log(f"  (取列表失败: {e})")
    return client, proc


def _pi_env(settings: Settings, controller_name: str, resource_name: str) -> dict[str, str]:
    """agent 需要的 PI_* 环境变量（等价于 MXU 启动 agent 时注入的那一组）。"""
    pi_ver, iface_ver = _pi_versions(settings)
    return {
        "PI_CONTROLLER": json.dumps(
            {
                "name": controller_name,
                "type": "Linux",
                "linux": {"screencap": "Wlr", "input": "Wlr", "use_win32_vk_code": True},
            },
            ensure_ascii=False,
        ),
        "PI_RESOURCE": json.dumps(
            {"name": resource_name, "path": [str(p) for p in settings.resource_dirs]},
            ensure_ascii=False,
        ),
        "PI_VERSION": pi_ver,
        "PI_CLIENT_NAME": "MXU",
        "PI_CLIENT_VERSION": pi_ver.lstrip("v").split("-")[0],
        "PI_CLIENT_LANGUAGE": "zh_cn",
        "PI_CLIENT_MAAFW_VERSION": "5.0.0",
        "PI_INTERFACE_VERSION": iface_ver,
    }


def _pi_versions(settings: Settings) -> tuple[str, str]:
    """从发行版 interface.json 读版本号，避免硬编码落后于实际资源。"""
    pi_ver, iface_ver = "unknown", "2"
    with contextlib.suppress(Exception):
        with open(Path(settings.root) / "interface.json", encoding="utf-8-sig") as f:
            iface = json.load(f)
        pi_ver = iface.get("version") or "unknown"
        iface_ver = str(iface.get("interfaceVersion") or 2)
    return pi_ver, iface_ver


def start_agents(
    res: Any,
    settings: Settings,
    *,
    controller_name: str = "Linux-Wlroots",
    resource_name: str = "官服-网页端",
    log: Log = print,
) -> list[tuple[Any, subprocess.Popen | None]]:
    """把 go-service 与 cpp-algo 都拉起来（缺 cpp-algo 时明确告警）。

    只起 go-service 时，MapFind / MapLocateAssertLocation / MapNavigateAction
    这些由 cpp-algo 注册的地图类能力全部缺失：传送锚点识别直接报
    `CustomRecognition.cpp recognition is null`，于是所有路由都点不到锚点，
    任务只会在开图/关图之间打转，永远走不到采集点。
    """
    bins = [Path(settings.agent_bin)]
    cpp = Path(settings.agent_bin).parent / CPP_ALGO
    if cpp.exists():
        bins.append(cpp)
    else:
        log("  ! 缺少 cpp-algo：传送锚点/走位类节点会全部失败")
    return [
        start_agent(
            res,
            settings,
            bin_path=b,
            tag=b.name,
            controller_name=controller_name,
            resource_name=resource_name,
            log=log,
        )
        for b in bins
    ]


def stop_agents(pairs: list[tuple[Any, subprocess.Popen | None]], log: Log = print) -> None:
    """收尾：terminate 所有 agent 进程（client 由 GC 关闭）。"""
    for _client, proc in pairs:
        if proc is None:
            continue
        with contextlib.suppress(Exception):
            proc.terminate()
            log(f"已关闭 agent (pid={proc.pid})")


def setup_tasker(tasker: Any, settings: Settings, log: Log = print) -> None:
    """tasker 一次性配置：stdout=Info、日志目录、可选识别可视化。"""
    try:
        from maa.define import LoggingLevelEnum

        tasker.set_stdout_level(LoggingLevelEnum.Info)  # 4：打印节点识别/动作轨迹
        # 日志目录必须可写：给 /root 下路径时框架会抛 C++ 异常直接 abort
        log_dir = Path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        tasker.set_log_dir(str(log_dir))
        # 识别可视化：MAA_SAVE_DRAW=1 时把每个节点的识别框/截图落盘到 <log_dir>/debug/
        # （默认关闭，一次全量会产出上百 MB）
        if os.environ.get("MAA_SAVE_DRAW") == "1":
            try:
                tasker.set_save_draw(True)
                tasker.set_save_on_error(True)
                tasker.set_draw_quality(85)
                log(f"  识别可视化已开启：draw/on_error -> {log_dir}/debug")
            except Exception as e:
                log(f"  (开启识别可视化失败: {str(e)[:60]})")
        log(f"  日志: stdout=Info  目录={log_dir}")
    except Exception as e:
        log(f"  (设置日志级别失败: {e})")
