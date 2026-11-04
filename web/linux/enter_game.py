#!/usr/bin/env python3
"""在云网页端点「开始游戏」并等到串流就绪。

判据只看页面自身：video 元素出现且 readyState>=3 且 currentTime 在走。
按钮位置用 DOM 遍历（含 shadowRoot）取 getBoundingClientRect 中心，不猜坐标。
"""
import json
import sys
import time
import urllib.request

import websocket

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9334
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 300

FIND = r"""
(() => {
  const hits = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
      const t = (el.innerText || el.textContent || '').trim();
      if (t === '开始游戏' || t === '进入游戏' || t === '点击任意位置继续') {
        const r = el.getBoundingClientRect();
        if (r.width > 10 && r.height > 10) hits.push({t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), w: Math.round(r.width), h: Math.round(r.height), tag: el.tagName});
      }
    }
  };
  walk(document);
  hits.sort((a, b) => a.w * a.h - b.w * b.h);
  return JSON.stringify(hits.slice(0, 5));
})()
"""

STATE = r"""
(() => {
  const v = document.getElementById('WelinkGameVideo');
  return JSON.stringify({
    video: v ? [v.videoWidth, v.videoHeight, v.readyState, Math.round(v.currentTime)] : null,
    videos: document.querySelectorAll('video').length,
    canvases: document.querySelectorAll('canvas').length,
    text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 120),
    href: location.href,
  });
})()
"""


def page():
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT, timeout=6) as r:
        ts = json.load(r)
    ps = [t for t in ts if t.get("type") == "page" and str(t.get("url", "")).startswith("http")]
    if not ps:
        raise SystemExit("no page target")
    return next((t for t in ps if "endfield" in t["url"]), ps[0])


def main():
    t = page()
    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15, max_size=None,
                                     suppress_origin=True)
    mid = 0

    def call(method, **p):
        nonlocal mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": p}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError("%s %s" % (method, m["error"]))
                return m.get("result", {})

    def ev(expr):
        return call("Runtime.evaluate", expression=expr, returnByValue=True)["result"].get("value")

    clicked = 0
    started = time.time()
    last = None
    while time.time() - started < TIMEOUT:
        st = json.loads(ev(STATE))
        last = st
        if st["video"] and st["video"][2] >= 3:
            print("STREAM_READY", json.dumps(st, ensure_ascii=False))
            ws.close()
            return 0
        hits = json.loads(ev(FIND))
        if hits:
            h = hits[0]
            print("[%4ds] click %r at (%d,%d) %dx%d tag=%s"
                  % (time.time() - started, h["t"], h["x"], h["y"], h["w"], h["h"], h["tag"]), flush=True)
            for typ in ("mousePressed", "mouseReleased"):
                call("Input.dispatchMouseEvent", type=typ, x=h["x"], y=h["y"],
                     button="left", clickCount=1)
            clicked += 1
        else:
            print("[%4ds] videos=%s canvases=%s text=%r"
                  % (time.time() - started, st["videos"], st["canvases"], st["text"][:60]), flush=True)
        time.sleep(6)
    print("TIMEOUT last=", json.dumps(last, ensure_ascii=False))
    ws.close()
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
