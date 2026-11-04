"""页面控制层：CDP 会话、页面状态机入口、策略注入、页面内输入（不含取帧）。

为什么单独一层：``--controller wlroots`` 时识别用的帧来自合成器（C++ ``Linux-Wlroots``），
但「页面现在在哪一态、怎么点开始游戏」只有页面自己知道，只能问 CDP。这一层不做取帧、
不做像素计算，所以留在 ``maaend_web`` 里而不是 ``devtools``。

与 :mod:`maaend_web.page` 的分工：``page`` 是纯状态机（求值 → 分支 → 动作，可离线单测），
本模块只提供它需要的 ``sess``（``call`` / ``ev``）与「把页面推进串流」的入口。

用法::

    ctl = PageControl(port=DEFAULT_PORT)
    if ctl.connect():
        ctl.prepare_page(timeout=90, log=print)
"""

import contextlib
import json
import threading
import urllib.request
from typing import Any

from . import page
from .config import DEFAULT_CDP_PORT
from .page import page_js

try:  # websocket-client 只在真正连浏览器时才需要，纯导入与 ruff 不依赖它
    import websocket  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    websocket = None

DEFAULT_PORT = DEFAULT_CDP_PORT
URL_HINT_DEFAULT = "endfield"


class Sess:
    """一条 CDP websocket 连接。抓帧线程与输入通道各用一条，互不阻塞。

    ``id`` 自增 + 只认自己 id 的响应：CDP 会把事件（``Page.*``、``Runtime.consoleAPICalled``）
    和响应混在同一条连接上，不匹配 id 就会把事件当成结果。
    """

    def __init__(self, url: str, timeout: float = 40.0):
        if websocket is None:
            raise RuntimeError("需要 websocket-client：python3 -m pip install websocket-client")
        self.ws = websocket.create_connection(url, timeout=timeout, suppress_origin=True)
        self.ws.settimeout(timeout)
        self._id = 0
        self.lock = threading.Lock()

    def call(self, method: str, **params):
        with self.lock:
            self._id += 1
            self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
            while True:
                r = json.loads(self.ws.recv())
                if r.get("id") == self._id:
                    if "error" in r:
                        raise RuntimeError(f"{method}: {str(r['error'])[:160]}")
                    return r.get("result", {})

    def ev(self, expr: str, await_p: bool = False):
        """``Runtime.evaluate`` 取值：``returnByValue`` 下结果在 ``result.result.value``。"""
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=await_p)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(str(res.get("description"))[:200])
        return res.get("value")

    def close(self):
        with contextlib.suppress(Exception):
            self.ws.close()


def target_url(port: int = DEFAULT_PORT, url_hint: str = URL_HINT_DEFAULT) -> str:
    """``/json/list`` 里挑一条 page target 的 websocket 地址；优先 url 含 ``url_hint`` 的。

    只认 ``http(s)`` 的 target：Chrome 自带的空白页也满足 ``type=page``，连上去永远抓不到帧。
    """
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=6) as resp:
        targets = json.loads(resp.read())
    pages = [
        t for t in targets if t.get("type") == "page" and str(t.get("url", "")).startswith(("http://", "https://"))
    ]
    if url_hint:
        pages = [t for t in pages if url_hint in (t.get("url") or "")] or pages
    if not pages:
        raise RuntimeError("没有 page target")
    return pages[0]["webSocketDebuggerUrl"]


def install_policy(io: Sess) -> bool:
    """把页面策略与抹平注入当前文档，并注册到之后每个新文档。

    两个动作缺一不可：``Page.addScriptToEvaluateOnNewDocument`` 管以后，``Runtime.evaluate``
    管当前（页面可能在我们连上之前就加载完了）。返回是否至少成功一条。
    """
    ok = False
    for src in (page_js.INPUT_POLICY_JS, page_js.FLATTEN_JS):
        with contextlib.suppress(Exception):
            io.call("Page.addScriptToEvaluateOnNewDocument", source=src)
            ok = True
        with contextlib.suppress(Exception):
            io.ev(src)
            ok = True
    return ok


class PageControl:
    """只做「页面状态机 + 注入 + 页面内输入」，不参与取帧。

    给 ``--controller wlroots`` 用：帧（识别输入）走合成器截图，启动链改问页面状态机，
    因此不再依赖 pipeline 的那 9 个启动节点，也不随控制器切换而失效。

        ctl = PageControl(); ctl.connect(); ctl.prepare_page()
    """

    def __init__(self, port: int = DEFAULT_PORT, url_hint: str = URL_HINT_DEFAULT):
        self.port = port
        self.url_hint = url_hint
        self._io: Sess | None = None

    def connect(self) -> bool:
        """连上 page target 并注入策略；连不上返回 False（调用方退回 pipeline 启动链）。"""
        try:
            self._io = Sess(target_url(self.port, self.url_hint))
            install_policy(self._io)
            return True
        except Exception:
            self._io = None
            return False

    def install_policy(self) -> bool:
        """重新注入一遍（幂等）；未连接时返回 False。"""
        if self._io is None:
            return False
        return install_policy(self._io)

    def page_state(self) -> page.State:
        """当前页面状态（结构化），给启动链和诊断用。"""
        if self._io is None:
            return page.State({"page": "unknown"})
        return page.inspect(self._io)

    def prepare_page(self, timeout: float = 90.0, log=None) -> bool:
        """把页面推进到「有解码帧」为止（页面状态机版启动链）。"""
        if self._io is None:
            return False
        return page.prepare(self._io, log=log or (lambda _m: None), timeout=timeout)

    def relative_move(self, dx: int, dy: int) -> bool:
        """相对移动：增量交给页面侧钩子，再发一条锚在视口中心的 mousemove 触发它。

        CDP 只有绝对坐标，直接推绝对坐标到边界就转不动了；而页面钩子只有在真的收到
        mousemove 时才改写 ``movementX/Y``，所以两步必须成对，少一步就是「返回 True 但画面不动」。
        """
        if self._io is None:
            return False
        try:
            ax, ay = page_js.RELATIVE_ANCHOR
            self._io.ev(f"window.__maaCloudRelativeMove && window.__maaCloudRelativeMove({int(dx)}, {int(dy)})")
            self._io.call(
                "Input.dispatchMouseEvent",
                type="mouseMoved",
                x=ax,
                y=ay,
                button="none",
                buttons=0,
                pointerType="mouse",
            )
            return True
        except Exception:
            return False

    def close(self) -> None:
        """关掉会话（可重复调用）。"""
        if self._io is not None:
            self._io.close()
            self._io = None

    def get_custom_info(self) -> dict[str, Any]:
        """诊断信息：端口与 hint，写进日志时用。"""
        return {"port": self.port, "url_hint": self.url_hint, "connected": self._io is not None}
