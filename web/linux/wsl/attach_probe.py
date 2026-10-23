#!/usr/bin/env python3
"""连上 launcher 起的浏览器，做一次「体检」：状态 / 注入 / 视口 / 截图。

手动测试用（不依赖 maafw）：
    python3 attach_probe.py --json /tmp/maaend-manual/launch.json --shot /mnt/d/qr.png
    python3 attach_probe.py --json ... --wait-ready 300    # 等扫码登录 + 进游戏

输出一行 JSON，字段：
    state  页面状态（page/account/video_ready/viewport…）
    checks 注入是否生效（flatten/policy/视口）
    shot   截图路径（如果给了 --shot）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))

import page_js  # noqa: E402
import page_state  # noqa: E402
from cdp_controller import _Sess  # noqa: E402

PROBE_JS = r"""
(() => {
  const c = document.createElement('canvas');
  const v = document.getElementById('WelinkGameVideo');
  return JSON.stringify({
    flattenTag: !!document.getElementById('maaend-flatten'),
    flattenCounter: window.__maaFlatten || null,
    relativeMove: typeof window.__maaCloudRelativeMove,
    webgl2Disabled: c.getContext('webgl2') === null,
    focusNoop: window.focus.length === 0,
    viewport: [innerWidth, innerHeight],
    dpr: devicePixelRatio,
    videoRect: v ? (r => [Math.round(r.width), Math.round(r.height)])(v.getBoundingClientRect()) : null
  });
})()
"""


def ws_url(port: int) -> str:
    import urllib.request
    ts = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5).read())
    pages = [t for t in ts if t.get("type") == "page"]
    if not pages:
        raise SystemExit("没有 page target")
    # 优先 endfield 页面
    hit = [t for t in pages if "endfield" in (t.get("url") or "")]
    return (hit or pages)[0]["webSocketDebuggerUrl"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="launcher --prepare 输出的 JSON 文件")
    ap.add_argument("--port", type=int, default=0, help="直接给 CDP 端口（优先于 --json）")
    ap.add_argument("--shot", help="截图保存路径（png）")
    ap.add_argument("--wait-ready", type=float, default=0, help="等 video_ready 的秒数")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    port = a.port
    if not port:
        if not a.json or not os.path.exists(a.json):
            raise SystemExit("需要 --port 或 --json")
        info = json.load(open(a.json, encoding="utf-8"))
        port = int((info.get("cdp") or "").rsplit(":", 1)[-1])

    sess = _Sess(ws_url(port))
    sess.call("Page.enable")
    sess.call("Runtime.enable")
    for src in (page_js.INPUT_POLICY_JS, page_js.FLATTEN_JS):
        sess.call("Page.addScriptToEvaluateOnNewDocument", source=src)
        sess.ev(src)

    st = page_state.inspect(sess)
    if a.wait_ready:
        deadline = time.time() + a.wait_ready
        last = ""
        while time.time() < deadline:
            st = page_state.inspect(sess)
            line = str(st)
            if line != last and not a.quiet:
                print("[等待] " + line, flush=True)
                last = line
            if st.video_ready:
                break
            if st.page == "login":
                print("[等待] 需要登录：打开截图扫码", flush=True)
            time.sleep(3)

    checks = json.loads(sess.ev(PROBE_JS))

    shot = None
    if a.shot:
        os.makedirs(os.path.dirname(os.path.abspath(a.shot)), exist_ok=True)
        r = sess.call("Page.captureScreenshot", format="png")
        import base64
        with open(a.shot, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        shot = a.shot

    print(json.dumps({"state": st.raw, "checks": checks, "shot": shot}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
