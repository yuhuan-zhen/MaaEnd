#!/usr/bin/env python3
"""诊断：页面为什么起不来。收集 console / log / 网络失败，重载后等 N 秒。

    python3 diagnose_page.py --json /tmp/maaend-manual/launch.json --wait 60
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

import websocket  # type: ignore


class CDP:
    def __init__(self, url: str):
        self.ws = websocket.create_connection(url, timeout=30, suppress_origin=True)
        self.i = 0

    def call(self, method: str, **params):
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.i:
                return m

    def drain(self, seconds: float, sink: list):
        """把事件收进 sink（不阻塞太久）。"""
        end = time.time() + seconds
        self.ws.settimeout(1.0)
        while time.time() < end:
            try:
                m = json.loads(self.ws.recv())
            except Exception:
                continue
            if "method" in m:
                sink.append(m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--wait", type=float, default=60)
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()

    port = a.port
    if not port:
        port = int(json.load(open(a.json, encoding="utf-8"))["cdp"].rsplit(":", 1)[-1])
    ts = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5).read())
    page = next(t for t in ts if t.get("type") == "page")

    c = CDP(page["webSocketDebuggerUrl"])
    for m in ("Runtime.enable", "Log.enable", "Network.enable", "Page.enable"):
        c.call(m)

    events: list = []
    print("reload…", flush=True)
    c.call("Page.reload", ignoreCache=True)
    c.drain(a.wait, events)

    logs, failed, http_err = [], [], []
    for e in events:
        m = e.get("method")
        p = e.get("params", {})
        if m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning"):
            args = " ".join(str(x.get("value", x.get("description", ""))) for x in p.get("args", []))
            logs.append("[console.%s] %s" % (p.get("type"), args[:300]))
        elif m == "Log.entryAdded":
            en = p.get("entry", {})
            if en.get("level") in ("error", "warning"):
                logs.append("[log.%s] %s %s" % (en.get("level"), en.get("text", "")[:200], en.get("url", "")[:120]))
        elif m == "Network.loadingFailed":
            failed.append("%s %s" % (p.get("errorText"), p.get("type")))
        elif m == "Network.responseReceived":
            r = p.get("response", {})
            if int(r.get("status", 0)) >= 400:
                http_err.append("%s %s" % (r.get("status"), r.get("url", "")[:140]))

    print("\n=== 控制台（最多 15 条）===")
    for line in logs[-15:]:
        print(" ", line)
    print("\n=== 网络失败（最多 15 条）===")
    for line in failed[-15:]:
        print(" ", line)
    print("\n=== HTTP >=400（最多 15 条）===")
    for line in http_err[-15:]:
        print(" ", line)

    st = c.call("Runtime.evaluate", expression="document.body.innerText.slice(0,300)", returnByValue=True)
    val = st.get("result", {}).get("result", {}).get("value")
    print("\n=== 页面文字 ===\n", (val or "")[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
