#!/usr/bin/env python3
"""运行期间按固定间隔抓 CDP 截图，用于事后定位「失败那一瞬间」的画面。

复用 :mod:`maaend_web.overlay` 的 target 筛选（只挑 page、url 命中 hint），每张落盘为
``f<序号>_<HHMMSS>.png``，同时打印路径与字节数。

用法::

    python3 web/linux/devtools/hs_capture.py --seconds 420 --interval 1.2 --out /tmp/frames

退出码：0 = 抓完（张数见 ``[i] done n=...``）；CDP 中途断开只重连重试，不算失败。
"""

import argparse
import base64
import contextlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websocket
from maaend_web.overlay import list_pages, select_targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9334)
    ap.add_argument("--seconds", type=float, default=420.0)
    ap.add_argument("--interval", type=float, default=1.2)
    ap.add_argument("--out", default="/tmp/frames")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    devtools = f"http://127.0.0.1:{a.port}"
    ws = None
    mid = 0
    n = 0
    t0 = time.time()

    while time.time() - t0 < a.seconds:
        if ws is None:
            try:
                targets = select_targets(list_pages(devtools))
            except Exception:
                targets = []
            if not targets:
                time.sleep(2.0)
                continue
            try:
                ws = websocket.create_connection(
                    targets[0]["webSocketDebuggerUrl"], timeout=10, suppress_origin=True
                )
                print(f"[i] connected {targets[0].get('url')}", flush=True)
            except Exception as exc:
                print(f"[warn] connect: {exc}", flush=True)
                ws = None
                time.sleep(2.0)
                continue

        mid += 1
        try:
            ws.send(json.dumps({"id": mid, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
            msg = None
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == mid:
                    break
            data = (msg or {}).get("result", {}).get("data")
            if data:
                n += 1
                path = os.path.join(a.out, f"f{n:04d}_{time.strftime('%H%M%S')}.png")
                with open(path, "wb") as fh:
                    fh.write(base64.b64decode(data))
                print(f"{path} {len(data)}", flush=True)
        except Exception as exc:
            print(f"[warn] capture: {exc}", flush=True)
            with contextlib.suppress(Exception):
                ws.close()
            ws = None
            time.sleep(1.0)
            continue

        time.sleep(a.interval)

    print(f"[i] done n={n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
