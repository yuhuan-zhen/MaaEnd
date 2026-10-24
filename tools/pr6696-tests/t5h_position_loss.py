#!/usr/bin/env python3
"""T5h · 位置差丢失检测（静止场景，灵敏度最高的一版）

已知机制（见 T5g）：客户端按**指针位置差**算旋转，不是 movementX。
因此要问的问题变成：

    快速连续的多段位移，有没有被合并/丢弃？
    不同发法（一次到位 / 6 小段连发 / 6 小段慢发）回到起点时，残差是否一致？

判据（关键）：+total 再 −total，画面应回到起点。
    残差 ≈ 噪声  → 该发法没有丢失
    残差 ≫ 噪声  → 有 delta 被吃掉（或相机平滑未收敛）

同时记 peak（到最远处时的画面差），用于确认确实转了。
静止场景噪声约 0.5，任何 3× 以上的残差都值得追。
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import statistics
import sys
import time

import cv2
import numpy as np

import _common as c

ANCHOR = 640
Y = 360
VIEW_ROI = (160, 560, 200, 1100)


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle

    def dispatch(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=Y, button="none", buttons=0)

    def reset(self) -> None:
        self.dispatch(ANCHOR)
        time.sleep(0.3)
        self.dispatch(ANCHOR)
        time.sleep(self.settle)

    def frame(self) -> np.ndarray:
        data = self.cdp.call("Page.captureScreenshot", format="png")["data"]
        raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def view(frame: np.ndarray) -> np.ndarray:
    y1, y2, x1, x2 = VIEW_ROI
    return frame[y1:y2, x1:x2].astype(np.int16)


def diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(view(a) - view(b)).mean())


def main() -> int:
    parser = argparse.ArgumentParser(description="T5h 位置差丢失检测")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--totals", default="240,480")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--settle", type=float, default=1.4)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    totals = [int(v) for v in args.totals.split(",")]
    modes = [("single", 1, 0.0), ("split6_fast", 6, 0.0), ("split6_slow", 6, 0.30)]
    evidence = c.Evidence("t5h", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, args.settle)

    # 噪声基线
    probe.reset()
    idle = []
    prev = probe.frame()
    for _ in range(4):
        time.sleep(args.settle)
        cur = probe.frame()
        idle.append(diff(prev, cur))
        prev = cur
    noise = statistics.median(idle)
    print(f"噪声基线 {noise:.3f}  样本 {[round(v, 2) for v in idle]}")
    if noise <= 0:
        print("噪声为 0，判据比值无意义，改用绝对阈值")
    result: dict = {"noise": round(noise, 3), "rows": []}

    print("\n模式            总量  峰值差    峰值/噪声   回位残差  残差/噪声")
    for total in totals:
        for name, pieces, gap in modes:
            for run in range(1, args.repeat + 1):
                probe.reset()
                base = probe.frame()
                # 分 pieces 段走到 ANCHOR+total
                for index in range(pieces):
                    target = round(total * (index + 1) / pieces)
                    probe.dispatch(ANCHOR + target)
                    if gap and index + 1 < pieces:
                        time.sleep(gap)
                time.sleep(args.settle)
                peak = probe.frame()
                # 一次回到锚点
                probe.dispatch(ANCHOR)
                time.sleep(args.settle)
                home = probe.frame()

                peak_diff = diff(base, peak)
                residual = diff(base, home)
                row = {
                    "mode": name, "total": total, "run": run,
                    "peak_diff": round(peak_diff, 2),
                    "peak_ratio": round(peak_diff / noise, 2) if noise else None,
                    "residual": round(residual, 2),
                    "residual_ratio": round(residual / noise, 2) if noise else None,
                }
                result["rows"].append(row)
                print(f"  {name:12s} {total:5d}  {peak_diff:7.2f}  "
                      f"{row['peak_ratio']:9.1f}  {residual:8.2f}  {row['residual_ratio']:8.1f}")

    # 汇总
    print("\n按模式汇总（中位）")
    for name, _, _ in modes:
        for total in totals:
            subset = [r for r in result["rows"] if r["mode"] == name and r["total"] == total]
            if not subset:
                continue
            peak = statistics.median([r["peak_ratio"] for r in subset])
            resid = statistics.median([r["residual_ratio"] for r in subset])
            tag = "无丢失" if resid < 3 else "可疑（残差偏高）"
            print(f"  {name:12s} total={total:4d}  峰值 {peak:6.1f}×  残差 {resid:6.1f}×  {tag}")

    print("\n判读")
    print("  峰值/噪声 > 10 说明确实转出去了")
    print("  残差/噪声 < 3  说明回到起点，未丢 delta")
    print("  若某模式残差明显偏高：该发法有 delta 被合并/丢弃，或相机平滑未收敛")
    evidence.write_json("summary.json", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
