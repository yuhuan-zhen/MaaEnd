#!/usr/bin/env python3
"""用**框架内置的 Linux 控制器**连一次，抓一帧存图。

这是「主形态」的验证：不写任何自定义控制器，只靠 MaaFramework 的 Wlr 控制单元。
手动用：
    python3 wlr_probe.py --sock /run/user/0/wayland-1 --shot /mnt/d/桌面/maaend-manual/wlr.png
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np  # noqa: F401  （screencap 返回 ndarray，缺包会在 maa 里炸）
from PIL import Image


def make(sock: str):
    try:
        from maa.controller import LinuxController

        return "LinuxController", LinuxController({
            "screencap_method": 1,   # Wlr
            "input_method": 1,       # Wlr
            "wlr_socket_path": sock,
            "use_win32_vk_code": True,
        })
    except ImportError:
        from maa.controller import WlRootsController

        return "WlRootsController", WlRootsController(sock, use_win32_vk_code=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", required=True, help="Wayland socket 路径（launcher 的 wlr 字段）")
    ap.add_argument("--shot", help="截图保存路径")
    ap.add_argument("--json", help="launcher 输出的 JSON（用它拿 wlr 字段）")
    a = ap.parse_args()

    sock = a.sock
    if a.json and os.path.exists(a.json):
        sock = json.load(open(a.json, encoding="utf-8")).get("wlr") or sock

    if not os.path.exists(sock):
        print(json.dumps({"ok": False, "error": "socket 不存在: %s" % sock}, ensure_ascii=False))
        return 2

    kind, ctrl = make(sock)
    job = ctrl.post_connection()
    job.wait()
    connected = bool(getattr(job, "succeeded", False))
    out = {"ok": connected, "kind": kind, "sock": sock, "connected": connected}
    if connected:
        img = ctrl.post_screencap().wait().get()
        if img is not None:
            out["shape"] = list(img.shape)
            out["dtype"] = str(img.dtype)
            out["mean"] = [round(float(img[:, :, i].mean()), 1) for i in range(img.shape[2])]
            if a.shot:
                os.makedirs(os.path.dirname(os.path.abspath(a.shot)), exist_ok=True)
                Image.fromarray(img[:, :, ::-1]).save(a.shot)
                out["shot"] = a.shot
    print(json.dumps(out, ensure_ascii=False))
    return 0 if connected else 1


if __name__ == "__main__":
    raise SystemExit(main())
