"""云网页端浮层控制：注入「页面策略 + 抹平」，探测悬浮球 / 延迟角标，文档替换后自愈。

本模块回答三件事：什么时候注入、注进去没有、文档换了以后失效没有。JS 只有一份，在
:mod:`maaend_web.page_js`：

- ``FLATTEN_JS`` 负责容器级隐藏与兜底（悬浮球 ``e4MbkW`` / ``hbU_7F``、延迟角标
  ``_gEApb`` / ``K_iy0u``，文本 ``\\d+ ms`` 命中后向上 lift 最多两层）；
- ``INPUT_POLICY_JS`` 是输入策略兜底（``document.hidden`` 覆写、无按键移动归零、
  拒绝指针锁定、禁 WebGL2、keydown 补 mouseenter），生产优先用 homesrv 的
  ``cloud_policy_linux.js``；
- ``PROBE_JS`` 供 ``--check`` 回读元素个数与隐藏状态。

``overlay_fingerprint()`` 把两套 class 指纹外露，方便云前端改版后核对选择器是否还命中。

为什么 watch 必须长连接：``Page.addScriptToEvaluateOnNewDocument`` 绑在 CDP session 上，
session 一关就失效（实测 ``counter`` 从 ``linux-2`` 变回 ``null``，页面上仍有 9ms 角标），
所以这里用「一条长连接 + 每轮 probe 判失效 + 失效重注入」。

为什么不把 ``cloud_policy_linux.js`` 与 ``INPUT_POLICY_JS`` 一起注入：两者的 mousemove 钩子
都会 ``Object.defineProperties(event, {movementX: …})``，这样定义出来的属性默认
non-configurable，先跑的那个会把后跑的直接顶成 TypeError，``relative_move`` 静默失效。
所以策略**二选一**：生产文件在就用它（homesrv 的部署形态），不在才退回 ``INPUT_POLICY_JS``。

用法与退出码见 :mod:`maaend_web.cli.overlay`（``--check`` / ``--once`` / ``--watch``）。
"""

import contextlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import page_js

try:  # websocket-client 只在真正连浏览器时才需要，纯函数测试不依赖它
    import websocket  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    websocket = None

DEVTOOLS_DEFAULT = "http://127.0.0.1:9334"
URL_HINT_DEFAULT = "endfield"
INJECT_METHOD = "Page.addScriptToEvaluateOnNewDocument"
EVAL_METHOD = "Runtime.evaluate"

# 已知外壳的 class 指纹（CSS Modules 哈希，随云前端改版会变）。
# 与 page_js.FLATTEN_JS 里的 BALL_SEL / PING_SEL 必须一致——tests/test_overlay_ctl.py 有断言。
BALL_SELECTORS = ('[class*="hbU_7F"]', '[class*="e4MbkW"]')
PING_SELECTORS = ('[class*="_gEApb"]', '[class*="K_iy0u"]')

# 生产版页面策略：homesrv 部署目录里的 cloud_policy_linux.js。
# 允许用环境变量换一份（改策略不用改代码）；找不到就退回 page_js.INPUT_POLICY_JS。
POLICY_ENV = "MAAEND_CLOUD_POLICY"
POLICY_FILENAME = "cloud_policy_linux.js"

# 注入后回读：证明脚本真的在这个文档里跑过（对应 hide_cloud_overlay 每轮打的 policy=/overlay=）。
POLICY_STATE_JS = (
    "JSON.stringify({policy: window.__hermesCloudPolicy || null,"
    " maa: !!window.__maaPolicyInstalled, flatten: window.__maaFlatten || null})"
)


def list_pages(devtools: str, timeout: float = 6.0) -> list[dict[str, Any]]:
    """读 CDP 的 ``/json/list``；连不上时抛 ``URLError``/``OSError``，由调用方翻译成退出码。"""
    url = devtools.rstrip("/") + "/json/list"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def select_targets(pages: list[dict[str, Any]], url_hint: str = URL_HINT_DEFAULT) -> list[dict[str, Any]]:
    """只挑 page 类型、url 含 hint 的 target；hint 为空时退化成全部 page。"""
    out = []
    for target in pages:
        if target.get("type") != "page":
            continue
        if not target.get("webSocketDebuggerUrl"):
            continue
        url = target.get("url") or ""
        if url_hint and url_hint.lower() not in url.lower():
            continue
        out.append(target)
    return out


def overlay_fingerprint() -> dict[str, list[str]]:
    """当前认识的悬浮球/延迟角标选择器（日志与改版核对用）。"""
    return {"ball": list(BALL_SELECTORS), "ping": list(PING_SELECTORS)}


# ---------------------------------------------------------------- 注入内容
def policy_candidates() -> list[Path]:
    """策略文件的候选路径，按优先级：环境变量 → ``web/linux/homesrv/`` → 包内自带。"""
    here = Path(__file__).resolve()
    out: list[Path] = []
    env = os.environ.get(POLICY_ENV)
    if env:
        out.append(Path(env))
    out.append(here.parent.parent / "homesrv" / POLICY_FILENAME)
    out.append(here.parent / POLICY_FILENAME)
    return out


def policy_path() -> Path | None:
    for cand in policy_candidates():
        if cand.is_file():
            return cand
    return None


def policy_source() -> str:
    """读页面策略 JS；读不到返回 ``''``（只跳过策略，不影响浮层隐藏）。

    刻意不做缓存：watch 常驻时改完 ``cloud_policy_linux.js`` 下一轮重注入就生效，不用重启。
    """
    path = policy_path()
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def inject_commands() -> list[tuple[str, dict[str, Any]]]:
    """抹平注入：先注册「之后每次导航都自动跑」，再对当前文档立刻跑一遍。

    与 ``CdpController.install_policy()`` 同序、同一份 ``page_js.FLATTEN_JS``，幂等
    （重复注入返回 ``'already'``）。上游契约是**恰好两条**，别往里加东西——策略走
    :func:`policy_commands`。
    """
    return [
        (INJECT_METHOD, {"source": page_js.FLATTEN_JS}),
        (EVAL_METHOD, {"expression": page_js.FLATTEN_JS, "returnByValue": True}),
    ]


def policy_commands(source: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    """页面策略注入，同样是「注册 + 当前文档」两连；没有策略文件时返回 ``[]``。"""
    src = policy_source() if source is None else source
    if not src:
        return []
    return [
        (INJECT_METHOD, {"source": src}),
        (EVAL_METHOD, {"expression": src, "returnByValue": True}),
    ]


def overlay_commands(policy: bool = True) -> list[tuple[str, dict[str, Any]]]:
    """一次注入的完整序列：策略在前（先修输入），抹平在后（再改 DOM）。"""
    return (policy_commands() if policy else []) + inject_commands()


# ---------------------------------------------------------------- 判读
def summarize(probe: dict[str, Any]) -> dict[str, Any]:
    """把 PROBE 结果压成一条日志：元素个数 + 已被抹平藏掉的个数 + 计数对象。"""
    pings = probe.get("ping") or []
    return {
        "version": probe.get("version"),
        "ball": len(probe.get("ball") or []),
        "ping": len(pings),
        "geo": len(probe.get("geo") or []),
        "hidden": sum(1 for p in pings if not p.get("shown", True)),
        "counter": probe.get("counter"),
    }


def needs_reinject(probe: dict[str, Any]) -> bool:
    """注入是否已经失效：文档被替换后 ``window.__maaFlatten`` 会消失。

    2026-11-02 实测：Chrome 的 ``Page.addScriptToEvaluateOnNewDocument`` 绑在 CDP session 上，
    session 一关（旧版 watch 每轮开/关连接）新文档就不再注入，页面上出现浮层但 counter 为 null。
    文档一换，策略脚本的 ``__hermesCloudPolicy`` / ``__maaPolicyInstalled`` 也一起消失，
    所以 ``counter`` 这一个判据同时覆盖「抹平丢了」和「策略丢了」。
    """
    if not probe.get("counter"):
        return True
    return any(p.get("shown") for p in (probe.get("ping") or []))


def all_hidden(probe: dict[str, Any]) -> bool:
    """True = 探测到的浮层全被藏掉（没有浮层也算 True）。"""
    return all(p.get("hiddenByFlatten") or not p.get("shown", True) for p in (probe.get("ping") or []))


# ---------------------------------------------------------------- 会话
class Sess:
    """一条 CDP websocket，只做 evaluate / 注入。

    长连接是 watch 的前提：``Page.addScriptToEvaluateOnNewDocument`` 注册在 session 上，
    连接一断，之后的新文档就没脚本可跑。
    """

    def __init__(self, url: str, timeout: float = 20.0):
        if websocket is None:
            raise RuntimeError("需要 websocket-client：python3 -m pip install websocket-client")
        self.ws = websocket.create_connection(url, timeout=timeout, suppress_origin=True)
        self.ws.settimeout(timeout)
        self._id = 0

    def call(self, method: str, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get("id") != self._id:
                continue  # 事件（Page.* / Runtime.*）没有 id，跳过
            if "error" in resp:
                raise RuntimeError(f"{method}: {str(resp['error'])[:160]}")
            return resp.get("result", {})

    def ev(self, expr: str):
        res = self.call(EVAL_METHOD, expression=expr, returnByValue=True).get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(str(res.get("description"))[:200])
        return res.get("value")

    def probe(self) -> dict[str, Any]:
        return json.loads(self.ev(page_js.PROBE_JS))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.ws.close()


def inject(sess: Sess, policy: bool = True) -> int:
    """把策略与抹平注入一个 target；返回发出的命令条数（``0`` 只可能是没东西可注）。"""
    cmds = overlay_commands(policy=policy)
    for method, params in cmds:
        sess.call(method, **params)
    return len(cmds)


def policy_state(sess: Sess) -> dict[str, Any]:
    """注入后回读页面里的策略/抹平标记；失败返回 ``{}``（纯诊断，不抛）。"""
    with contextlib.suppress(Exception):
        raw = sess.ev(POLICY_STATE_JS)
        if raw:
            return json.loads(raw)
    return {}


def _probe_or_reinject(sess: Sess, *, force: bool, policy: bool) -> tuple[dict[str, Any], str]:
    """取一次 probe；``force`` 或判到失效就重注入再取。返回 ``(probe, 动作)``。"""
    if force:
        inject(sess, policy=policy)
        return sess.probe(), "injected"
    probe = sess.probe()
    if needs_reinject(probe):
        inject(sess, policy=policy)
        return sess.probe(), "reinjected"
    return probe, "probe"


def _tag(target: dict[str, Any]) -> str:
    return str(target.get("id") or "")[:8] or "unknown"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _targets(devtools: str, url_hint: str, log) -> list[dict[str, Any]] | None:
    """``/json/list`` + 过滤；连不上返回 ``None``（调用方据此退 2）。"""
    try:
        pages = list_pages(devtools)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log(f"devtools unreachable: {exc}")
        return None
    return select_targets(pages, url_hint)


def _policy_note() -> str:
    path = policy_path()
    if path is None:
        return f"policy=missing（只注入抹平；设置 {POLICY_ENV} 或放回 homesrv/{POLICY_FILENAME}）"
    return f"policy={path}"


# ---------------------------------------------------------------- 三个动作
def run_check(devtools: str, url_hint: str) -> int:
    """只探测。退出码：0 全隐藏 / 1 有残留（或连不上某个 target）/ 2 连不上 CDP 或无 target。"""
    targets = _targets(devtools, url_hint, _log)
    if targets is None:
        return 2
    if not targets:
        _log(f"no target (hint={url_hint!r})")
        return 2
    bad = 0
    errors = 0
    for target in targets:
        try:
            sess = Sess(target["webSocketDebuggerUrl"])
            try:
                probe = sess.probe()
            finally:
                sess.close()
        except Exception as exc:
            errors += 1
            bad += 1
            _log(f"{_tag(target)} error: {exc}")
            continue
        _log(f"{_tag(target)} probe={json.dumps(probe, ensure_ascii=False)}")
        if not all_hidden(probe):
            bad += 1
            _log(f"{_tag(target)} residual={json.dumps(summarize(probe), ensure_ascii=False)}")
    if bad == 0:
        return 0
    return 2 if errors == len(targets) else 1


def run_once(devtools: str, url_hint: str, *, policy: bool = True) -> int:
    """注入一次（所有匹配 target）。退出码：0 全部注入成功 / 1 有 target 注入失败 / 2 连不上或无 target。"""
    targets = _targets(devtools, url_hint, _log)
    if targets is None:
        return 2
    if not targets:
        _log(f"no target (hint={url_hint!r})")
        return 2
    _log(_policy_note())
    failed = 0
    for target in targets:
        try:
            sess = Sess(target["webSocketDebuggerUrl"])
            try:
                n = inject(sess, policy=policy)
                probe = sess.probe()
                state = policy_state(sess)
            finally:
                sess.close()
        except Exception as exc:
            failed += 1
            _log(f"{_tag(target)} inject failed: {exc}")
            continue
        _log(
            f"{_tag(target)} injected cmds={n} state={json.dumps(state, ensure_ascii=False)}"
            f" overlay={json.dumps(summarize(probe), ensure_ascii=False)}"
        )
        if not all_hidden(probe):
            # 不算失败：新注入的文档可能还没触发 MutationObserver，且 --once 的契约是「注入成功」。
            _log(f"{_tag(target)} warn: 仍有可见浮层，见上面 overlay 计数")
    return 0 if failed == 0 else 1


def run_watch(
    devtools: str,
    url_hint: str,
    interval: float = 2.0,
    probe_every: float = 30.0,
    *,
    policy: bool = True,
) -> int:
    """常驻：每个 target 保持**一条长连接**，新 target 立刻注入，已注入的定期探测/自愈。

    为什么必须长连接：``Page.addScriptToEvaluateOnNewDocument`` 绑在 CDP session 上，
    session 一关就失效（2026-11-02 在真实会话上实测：``counter`` 从 linux-2 变回 null，
    页面上仍然有 9ms 角标）。短连接版本只能注入当前文档，文档一换就等于没注入。
    """
    sessions: dict[str, Sess] = {}
    last_probe: dict[str, float] = {}
    installed: set[str] = set()
    _log(_policy_note())
    try:
        while True:
            try:
                pages = list_pages(devtools)
            except Exception as exc:
                _log(f"devtools unreachable: {exc}")
                for tid in list(sessions):
                    sessions.pop(tid).close()
                last_probe.clear()
                installed.clear()
                time.sleep(interval)
                continue

            alive = {_tag(t): t for t in select_targets(pages, url_hint)}
            for tid in list(sessions):
                if tid not in alive:
                    sessions.pop(tid).close()
                    last_probe.pop(tid, None)
                    installed.discard(tid)

            for tid, target in alive.items():
                sess = sessions.get(tid)
                fresh = sess is None
                if fresh:
                    try:
                        sess = Sess(target["webSocketDebuggerUrl"])
                    except Exception as exc:
                        _log(f"{tid} connect failed: {exc}")
                        continue
                    sessions[tid] = sess

                now = time.time()
                if not fresh and tid in last_probe and now - last_probe[tid] < probe_every:
                    continue
                try:
                    probe, action = _probe_or_reinject(sess, force=fresh or tid not in installed, policy=policy)
                except Exception as exc:
                    _log(f"{tid} error: {exc}")
                    sessions.pop(tid).close()
                    last_probe.pop(tid, None)
                    installed.discard(tid)
                    continue
                installed.add(tid)
                last_probe[tid] = now
                state = policy_state(sess) if action != "probe" else None
                extra = f" state={json.dumps(state, ensure_ascii=False)}" if state is not None else ""
                _log(f"{tid} {action}{extra} overlay={json.dumps(summarize(probe), ensure_ascii=False)}")
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        for sess in sessions.values():
            sess.close()


def main(argv: list[str] | None = None) -> int:
    """兼容 shim：``web/linux/overlay_ctl.py`` 里 ``python overlay_ctl.py`` 仍能跑。

    真正的 argparse 在 ``maaend_web.cli.overlay``（本模块不碰命令行解析）。
    """
    from .cli.overlay import main as cli_main

    return cli_main(argv)
