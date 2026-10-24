#!/usr/bin/env python3
"""T5c · 用「同总量两种拆法」判定 >127 是否被截断（不依赖角度读取）

思路：
    总量 T 有两种发法
      S1：一次发完    movementX = T
      S2：拆成 k 段   每段 ≤127（k = ceil(T/127)）
    若不存在截断，两种发法总转角相同 → 最终画面应当几乎一致；
    若存在 clamp@127，S1 只转了 127 对应的角度 → 两者画面差异巨大；
    若存在 wrap@128（8 位溢出），S1 会反向转 → 差异更大。

度量：两帧的平均像素差，与「完全没动」的噪声基线比较。
    噪声基线 = 连续两帧（不发任何输入）的差异中位数。
    判据：ratio = diff(F1,F2) / noise
        ratio < 3     → 两种拆法等效 → 该总量下无截断
        ratio ≥ 3     → 不等效 → 有截断（或发了丢失）

额外记录箭头角度（rot）——本测试不依赖它，只作参考：如果角色不跟随镜头，
它不会变，这不影响结论。

用法：
    python3 t5c_split_equivalence.py --port 9334
    python3 t5c_split_equivalence.py --port 9334 --totals 200,360 --repeat 2
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import pathlib
import statistics
import sys
import time

import cv2
import numpy as np

import _common as c
import arrow_ruler as ruler

ANCHOR = (640, 360)
MAX_STEP = 127
UNITS_PER_DEGREE = 4.0
VIEW_ROI = (160, 560, 200, 1100)   # y1,y2,x1,x2：画面中部，避开 HUD


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle
        self.x = ANCHOR[0]

    def dispatch(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=ANCHOR[1],
                      button="none", buttons=0)
        self.x = x

    def reset(self) -> None:
        """回到锚点并稳定（第二次原地移动 delta=0）。"""
        self.dispatch(ANCHOR[0])
        time.sleep(0.25)
        self.dispatch(ANCHOR[0])
        time.sleep(self.settle)

    def send(self, total: int, pieces: int = 1, gap: float = 0.15) -> None:
        """把 total 拆成 pieces 段发出，终点为 anchor+total。"""
        travelled = 0
        for index in range(pieces):
            target = round(total * (index + 1) / pieces)
            self.dispatch(ANCHOR[0] + target)
            travelled = target
            if index + 1 < pieces:
                time.sleep(gap)
        del travelled

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
    parser = argparse.ArgumentParser(description="T5c 拆分等效性测试")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--totals", default="200,254,360", help="待测总量（逗号分隔）")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--settle", type=float, default=1.0)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    totals = [int(v) for v in args.totals.split(",")]
    evidence = c.Evidence("t5c", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    probe = Probe(args.port, args.settle)
    result: dict = {"totals": [], "noise": None}

    # 噪声基线：不动，连拍 4 帧，取相邻差的中位数
    probe.reset()
    idle = []
    prev = probe.frame()
    for _ in range(4):
        time.sleep(0.9)
        cur = probe.frame()
        idle.append(diff(prev, cur))
        prev = cur
    noise = statistics.median(idle)
    result["noise"] = round(noise, 3)
    print(f"噪声基线（不动作的帧间差）：{noise:.2f}  样本 {[round(v, 1) for v in idle]}")

    for total in totals:
        pieces = math.ceil(total / MAX_STEP)
        rows = []
        for run in range(1, args.repeat + 1):
            # S2：拆开
            probe.reset()
            base = probe.frame()
            probe.send(total, pieces=pieces)
            time.sleep(args.settle)
            split_frame = probe.frame()
            split_angle = ruler.angle_of_frame(split_frame)
            moved_diff = diff(base, split_frame)

            # 回位
            probe.dispatch(ANCHOR[0])
            time.sleep(args.settle)
            back_frame = probe.frame()
            back_diff = diff(base, back_frame)

            # S1：一次发完
            probe.reset()
            probe.send(total, pieces=1)
            time.sleep(args.settle)
            single_frame = probe.frame()
            single_angle = ruler.angle_of_frame(single_frame)

            # 回位
            probe.dispatch(ANCHOR[0])
            time.sleep(args.settle)

            cross = diff(split_frame, single_frame)
            ratio = cross / noise if noise > 0 else float("inf")
            rows.append({
                "run": run, "total": total, "pieces": pieces,
                "diff_split_vs_base": round(moved_diff, 2),
                "diff_back_vs_base": round(back_diff, 2),
                "diff_split_vs_single": round(cross, 2),
                "ratio_to_noise": round(ratio, 2),
                "angle_split": round(split_angle, 1), "angle_single": round(single_angle, 1),
            })
            print(f"  T={total:3d} 拆{pieces}段 run={run}："
                  f"动后差 {moved_diff:6.2f}  回位差 {back_diff:5.2f}  "
                  f"两种拆法差 {cross:6.2f}  = {ratio:5.2f}× 噪声")

        ratios = [row["ratio_to_noise"] for row in rows]
        verdict = "无截断（两种拆法等效）" if statistics.median(ratios) < 3 else "有截断（两种拆法不等效）"
        result["totals"].append({"total": total, "pieces": pieces,
                                 "median_ratio": round(statistics.median(ratios), 2),
                                 "verdict": verdict, "runs": rows})
        print(f"  → T={total}: 中位比值 {statistics.median(ratios):.2f}  {verdict}")

    evidence.write_json("summary.json", result)

    print("\n判读")
    print("  比值 ≈1 → 两种拆法转的角度一样，说明大位移没有被截断")
    print("  比值 ≫1 → 一次发 T 与实际拆开发 T 的结果不同，说明有截断或丢步")
    print("  箭头角度仅作参考：角色不跟镜头时它不会变，不影响本判定")
    return 0


if __name__ == "__main__":
    sys.exit(main())
