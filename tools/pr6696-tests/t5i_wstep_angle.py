#!/usr/bin/env python3
"""T5i · 用「走一步」把镜头角转成角色角，测 units/度

原理：
    rot（小地图箭头）= 角色朝向；角色移动方向 = 镜头前方。
    所以「转镜头 → 按 W 走一小段 → 角色转身面向移动方向」之后，
    rot 的变化量 ≈ 镜头转角。

    这样就不需要 camRot，也不需要任何绝对角度模型，只要已验证的箭头尺子（1.41°）。

判据：
    180 units 若 ≈ 45°  → 4 units/度（#6807 的 kDefaultTurnUnitsPerDegree）
    180 units 若 ≈ 90°  → 2 units/度（Go CharacterController 的 delta×2）
    180 units 若 ≈ 22.7°→ 7.93 units/度（MapNavigator Win32 的 kTurn360UnitsPerWidth）

用法：
    python3 t5i_wstep_angle.py --port 9334 --dx-list 0,180,360 --repeat 3
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
import arrow_ruler as ruler

ANCHOR = 640
Y = 360
VK_W = 87


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle

    def dispatch(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=Y, button="none", buttons=0)

    def key(self, down: bool) -> None:
        params = {
            "type": "keyDown" if down else "keyUp",
            "windowsVirtualKeyCode": VK_W,
            "nativeVirtualKeyCode": VK_W,
            "code": "KeyW",
            "key": "w",
        }
        if down:
            params["text"] = "w"
        self.cdp.call("Input.dispatchKeyEvent", **params)

    def frame(self) -> np.ndarray:
        data = self.cdp.call("Page.captureScreenshot", format="png")["data"]
        raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def rot(self, tries: int = 3) -> float:
        for _ in range(tries):
            value = ruler.angle_of_frame(self.frame())
            if value >= 0:
                return value
            time.sleep(0.2)
        return -1.0

    def reset_pointer(self) -> None:
        self.dispatch(ANCHOR)
        time.sleep(0.3)
        self.dispatch(ANCHOR)
        time.sleep(self.settle)

    def walk(self, ms: int, pulses: int = 1) -> None:
        """分 pulses 段走。角色转身有速率上限，单段走不够会只转一部分。"""
        for _ in range(max(1, pulses)):
            self.key(True)
            time.sleep(ms / 1000.0)
            self.key(False)
            time.sleep(0.45)

    def sync(self, ms: int, pulses: int = 1) -> None:
        """走几步让角色朝向对齐镜头前方（这是一切测量的前提）。"""
        self.walk(ms, pulses)


def main() -> int:
    parser = argparse.ArgumentParser(description="T5i 走一步测转角")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--dx-list", default="0,180,360")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--walk-ms", type=int, default=350, help="每次按 W 的时长")
    parser.add_argument("--walk-pulses", type=int, default=3, help="走几段（转弯有速率上限，太少转不完）")
    parser.add_argument("--pieces", type=int, default=1, help="把 dx 拆成几段发（1 = 一次到位）")
    parser.add_argument("--piece-gap", type=float, default=0.06, help="分段之间的间隔（秒）")
    parser.add_argument("--settle", type=float, default=1.3)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    steps = [int(v) for v in args.dx_list.split(",")]
    evidence = c.Evidence("t5i", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, args.settle)

    rows: list[dict] = []
    for dx in steps:
        print(f"\n== dx={dx} units ==")
        for run in range(1, args.repeat + 1):
            probe.reset_pointer()
            probe.sync(args.walk_ms, args.walk_pulses)   # 先对齐：rot ← 镜头前方
            a0 = probe.rot()
            if a0 < 0:
                print("  起始读不出，跳过")
                continue
            if dx:
                # 拆成 pieces 段：指针停在视口内，每段位移 = dx/pieces
                for index in range(args.pieces):
                    probe.dispatch(ANCHOR + round(dx * (index + 1) / args.pieces))
                    if args.piece_gap and index + 1 < args.pieces:
                        time.sleep(args.piece_gap)
                time.sleep(args.settle)
            probe.sync(args.walk_ms, args.walk_pulses)   # 再对齐：rot 跟上新镜头方向
            a2 = probe.rot()
            if a2 < 0:
                print("  结束读不出，跳过")
                continue
            delta = ruler.circular_delta(a0, a2)
            rows.append({"dx": dx, "run": run, "a0": round(a0, 1), "a2": round(a2, 1),
                         "delta": round(delta, 1)})
            print(f"  run={run}  rot {a0:6.1f}° → {a2:6.1f}°   Δ {delta:+7.1f}°")

    print("\n汇总（每档中位）")
    print("  dx   Δ中位(°)   隐含 units/度   对照假设")
    summary = []
    for dx in steps:
        values = [abs(r["delta"]) for r in rows if r["dx"] == dx]
        if not values:
            continue
        median = statistics.median(values)
        per_degree = dx / median if median > 1.0 else float("inf")
        tag = ""
        if median > 1.0:
            if abs(median - 45) < 12:
                tag = "≈4 units/度（#6807）"
            elif abs(median - 90) < 12:
                tag = "≈2 units/度（Go delta×2）"
            elif abs(median - 22.7) < 8:
                tag = "≈7.93 units/度（MapNavigator Win32）"
            else:
                tag = f"{per_degree:.2f} units/度"
        summary.append({"dx": dx, "median_delta": round(median, 1),
                        "units_per_degree": round(per_degree, 2) if per_degree != float("inf") else None})
        print(f"  {dx:4d}  {median:8.1f}   {per_degree:12.2f}   {tag}")

    if len(summary) >= 2 and summary[0]["median_delta"] > 1:
        ratio = summary[-1]["median_delta"] / summary[0]["median_delta"]
        expected = summary[-1]["dx"] / summary[0]["dx"] if summary[0]["dx"] else 0
        print(f"\n比例校验：Δ({summary[-1]['dx']}) / Δ({summary[0]['dx']}) = {ratio:.2f}"
              f"（若线性应 ≈ {expected:.2f}）")

    evidence.write_json("summary.json", {"rows": rows, "summary": summary})
    print("\n判读提示")
    print("  1. 若 Δ(dx=0) 明显不为 0，说明「走一步」本身会改变朝向，需先扣掉基线")
    print("  2. 若各档 Δ 不成比例，说明转身动画/惯性在污染，需要加长稳定时间")
    return 0


if __name__ == "__main__":
    sys.exit(main())
