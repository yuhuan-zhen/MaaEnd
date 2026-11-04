#!/usr/bin/env python3
"""模板重抠工具：从整帧裁出新模板、落到覆盖层、当场自校验（坐标按控制器帧 1280×720）。

依赖 OpenCV（`apt install python3-opencv` 或 `pip install opencv-python-headless`）。

用法：

  # 1) 看某模板在当前帧上的最佳匹配位置（决定往哪裁）
  python3 web/linux/recapture_template.py probe \\
      --frame frame.png --template ~/maaend/resource/image/EssenceFilter/EssenceTabNotChoose.png

  # 2) 从帧里裁一块当新模板
  python3 web/linux/recapture_template.py crop \\
      --frame frame.png --x 690 --y 0 --w 37 --h 35 \\
      --out web/resource_web/image/EssenceFilter/EssenceTabNotChoose.png \\
      --meta "EssenceFilter 失败帧 2026-10-26"

  # 3) 多帧校验同一模板
  python3 web/linux/recapture_template.py check \\
      --template web/resource_web/image/EssenceFilter/EssenceTabNotChoose.png \\
      --frame a.png --frame b.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import cv2
    import numpy as np
except ImportError as exc:
    raise SystemExit(
        "需要 OpenCV 与 numpy：apt install python3-opencv 或 pip install opencv-python-headless"
    ) from exc


def load(path: str):
    """读图，兼容非 ASCII 路径。"""
    buf = np.fromfile(path, dtype=np.uint8)
    if buf.size == 0:
        raise SystemExit("读不到图片: %s" % path)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("解码失败: %s" % path)
    return img


def save(img, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise SystemExit("编码失败: %s" % path)
    buf.tofile(path)


def best_match(img, tpl):
    if img.shape[0] < tpl.shape[0] or img.shape[1] < tpl.shape[1]:
        return -1.0, None
    r = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _, mx, _, ml = cv2.minMaxLoc(r)
    return float(mx), (int(ml[0]), int(ml[1]))


def cmd_probe(a) -> None:
    frame, tpl = load(a.frame), load(a.template)
    score, loc = best_match(frame, tpl)
    print(json.dumps({
        "frame": a.frame, "template": a.template,
        "frame_size": [int(frame.shape[1]), int(frame.shape[0])],
        "tpl_size": [int(tpl.shape[1]), int(tpl.shape[0])],
        "score": round(score, 4), "at": loc,
        "suggest_crop": ({"x": loc[0], "y": loc[1],
                          "w": int(tpl.shape[1]), "h": int(tpl.shape[0])} if loc else None),
    }, ensure_ascii=False, indent=1))


def cmd_crop(a) -> None:
    frame = load(a.frame)
    h, w = frame.shape[:2]
    if a.w <= 0 or a.h <= 0:
        raise SystemExit("--w/--h 必须是正数")
    if a.x < 0 or a.y < 0 or a.x + a.w > w or a.y + a.h > h:
        raise SystemExit("裁剪框 (x=%d,y=%d,w=%d,h=%d) 超出画面 %dx%d" % (a.x, a.y, a.w, a.h, w, h))
    piece = frame[a.y:a.y + a.h, a.x:a.x + a.w].copy()
    save(piece, a.out)
    score, loc = best_match(frame, piece)
    print(json.dumps({"out": a.out, "size": [a.w, a.h], "self_match": round(score, 4),
                      "found_at": loc, "meta": a.meta or ""}, ensure_ascii=False, indent=1))


def cmd_check(a) -> None:
    tpl = load(a.template)
    out = []
    for f in a.frame:
        s, loc = best_match(load(f), tpl)
        out.append({"frame": f, "score": round(s, 4), "at": loc})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description="模板重抠工具（1280×720 坐标系）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("probe", help="看模板在帧上的最佳位置")
    p1.add_argument("--frame", required=True)
    p1.add_argument("--template", required=True)
    p1.set_defaults(func=cmd_probe)

    p2 = sub.add_parser("crop", help="从帧裁出新模板并落到覆盖层")
    p2.add_argument("--frame", required=True)
    p2.add_argument("--x", type=int, required=True)
    p2.add_argument("--y", type=int, required=True)
    p2.add_argument("--w", type=int, required=True)
    p2.add_argument("--h", type=int, required=True)
    p2.add_argument("--out", required=True)
    p2.add_argument("--meta", default="")
    p2.set_defaults(func=cmd_crop)

    p3 = sub.add_parser("check", help="多帧校验一个模板")
    p3.add_argument("--template", required=True)
    p3.add_argument("--frame", action="append", required=True)
    p3.set_defaults(func=cmd_check)

    a = ap.parse_args()
    a.func(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
