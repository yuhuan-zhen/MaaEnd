#!/usr/bin/env python3
"""云网页端浮层控制：注入抹平策略、探测延迟角标 / 悬浮球。

本脚本是 ``cdp_controller.install_policy()`` 之外的**外部入口**：给「浏览器已经跑起来、
但没经过 run_daily_linux」的场景用（例如 MXU 自己拉起的 Chrome、调试时手工开的会话）。
两者注入的是同一份 ``page_js.FLATTEN_JS``，幂等，重复注入返回 ''already''。

用法::

    python3 overlay_ctl.py --check                  # 只探测，逐个 target 打 JSON
    python3 overlay_ctl.py --once                   # 注入一次（所有 endfield 页）
    python3 overlay_ctl.py --watch                  # 常驻：新 target 注入，已注入的定期探测
    python3 overlay_ctl.py --check --port 9334 --url-hint endfield

``--check`` 的退出码：0 全部已隐藏 / 1 仍有可见浮层 / 2 没有可用 target。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.request
from typing import Any

import page_js

try:  # websocket-client 只在真正连浏览器时才需要，纯函数测试不依赖它
    import websocket  # type: ignore
except ImportError:  # pragma: no cover
    websocket = None

DEVTOOLS_DEFAULT = "http://127.0.0.1:9334"
URL_HINT_DEFAULT = "endfield"
INJECT_METHOD = "Page.addScriptToEvaluateOnNewDocument"


def list_pages(devtools: str, timeout: float = 6.0) -> list[dict[str, Any]]:
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


def inject_commands() -> list[tuple[str, dict[str, Any]]]:
    """与 install_policy 同序：先让之后每次导航都自动注入，再对当前文档立刻跑一遍。"""
    return [
        (INJECT_METHOD, {"source": page_js.FLATTEN_JS}),
        ("Runtime.evaluate", {"expression": page_js.FLATTEN_JS, "returnByValue": True}),
    ]


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
    """
    if not probe.get("counter"):
        return True
    return any(p.get("shown") for p in (probe.get("ping") or []))


def all_hidden(probe: dict[str, Any]) -> bool:
    """True = 探测到的浮层全被藏掉（没有浮层也算 True）。"""
    return all(p.get("hiddenByFlatten") or not p.get("shown", True) for p in (probe.get("ping") or []))


class Sess:
    """一条 CDP websocket，只做 evaluate / 注入。"""

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
                continue
            if "error" in resp:
                raise RuntimeError(f"{method}: {str(resp['error'])[:160]}")
            return resp.get("result", {})

    def ev(self, expr: str):
        res = self.call("Runtime.evaluate", expression=expr, returnByValue=True).get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(str(res.get("description"))[:200])
        return res.get("value")

    def probe(self) -> dict[str, Any]:
        return json.loads(self.ev(page_js.PROBE_JS))

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.ws.close()


def inject(sess: Sess) -> None:
    for method, params in inject_commands():
        sess.call(method, **params)


def _tag(target: dict[str, Any]) -> str:
    return str(target.get("id") or "")[:8] or "unknown"


def _log(msg: str) -> None:
    print(msg, flush=True)


def run_check(devtools: str, url_hint: str) -> int:
    pages = list_pages(devtools)
    targets = select_targets(pages, url_hint)
    if not targets:
        _log(f"no target (pages={len(pages)} hint={url_hint!r})")
        return 2
    bad = 0
    for target in targets:
        sess = Sess(target["webSocketDebuggerUrl"])
        try:
            probe = sess.probe()
        finally:
            sess.close()
        _log(f"{_tag(target)} probe={json.dumps(probe, ensure_ascii=False)}")
        if not all_hidden(probe):
            bad += 1
    return 0 if bad == 0 else 1


def run_once(devtools: str, url_hint: str) -> int:
    pages = list_pages(devtools)
    targets = select_targets(pages, url_hint)
    if not targets:
        _log(f"no target (pages={len(pages)} hint={url_hint!r})")
        return 2
    for target in targets:
        sess = Sess(target["webSocketDebuggerUrl"])
        try:
            inject(sess)
            probe = sess.probe()
        finally:
            sess.close()
        summary = summarize(probe)
        _log(f"{_tag(target)} injected overlay={json.dumps(summary, ensure_ascii=False)}")
    return 0


def run_watch(devtools: str, url_hint: str, interval: float, probe_every: float) -> int:
    """常驻：每个 target 保持**一条长连接**，新 target 立刻注入并探测。

    为什么必须长连接：``Page.addScriptToEvaluateOnNewDocument`` 绑在 CDP session 上，
    session 一关就失效（2026-11-02 在真实会话上实测：``counter`` 从 linux-2 变回 null，
    页面上仍然有 9ms 角标）。短连接版本只能注入当前文档，文档一换就等于没注入。
    """
    sessions: dict[str, Sess] = {}
    last_probe: dict[str, float] = {}
    try:
        while True:
            try:
                pages = list_pages(devtools)
            except Exception as exc:
                _log(f"devtools unreachable: {exc}")
                for tid in list(sessions):
                    sessions.pop(tid).close()
                last_probe.clear()
                time.sleep(interval)
                continue

            alive = {_tag(t): t for t in select_targets(pages, url_hint)}
            for tid in list(sessions):
                if tid not in alive:
                    sessions.pop(tid).close()
                    last_probe.pop(tid, None)

            for tid, target in alive.items():
                sess = sessions.get(tid)
                if sess is None:
                    try:
                        sess = Sess(target["webSocketDebuggerUrl"])
                    except Exception as exc:
                        _log(f"{tid} connect failed: {exc}")
                        continue
                    sessions[tid] = sess

                now = time.time()
                if tid in last_probe and now - last_probe[tid] < probe_every:
                    continue
                try:
                    probe = sess.probe()
                    if needs_reinject(probe):
                        inject(sess)
                        probe = sess.probe()
                except Exception as exc:
                    _log(f"{tid} error: {exc}")
                    sessions.pop(tid).close()
                    last_probe.pop(tid, None)
                    continue
                last_probe[tid] = now
                _log(f"{tid} overlay={json.dumps(summarize(probe), ensure_ascii=False)}")
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    finally:
        for sess in sessions.values():
            sess.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="云网页端浮层控制（注入 page_js.FLATTEN_JS / 用 PROBE_JS 探测）")
    ap.add_argument("--devtools", default=DEVTOOLS_DEFAULT, help="CDP HTTP 端点，默认 %(default)s")
    ap.add_argument("--port", type=int, default=None, help="只给端口时等价于 http://127.0.0.1:<port>")
    ap.add_argument("--url-hint", default=URL_HINT_DEFAULT, help="只处理 url 含该串的 page，默认 %(default)s")
    ap.add_argument("--check", action="store_true", help="只探测并打印 JSON")
    ap.add_argument("--once", action="store_true", help="注入一次")
    ap.add_argument("--watch", action="store_true", help="常驻巡检")
    ap.add_argument("--interval", type=float, default=2.0, help="watch 轮询间隔秒，默认 %(default)s")
    ap.add_argument(
        "--probe-every", type=float, default=30.0, help="watch 里已注入 target 的探测间隔秒，默认 %(default)s"
    )
    args = ap.parse_args(argv)

    devtools = f"http://127.0.0.1:{args.port}" if args.port else args.devtools
    if args.check:
        return run_check(devtools, args.url_hint)
    if args.watch:
        return run_watch(devtools, args.url_hint, args.interval, args.probe_every)
    if args.once:
        return run_once(devtools, args.url_hint)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
