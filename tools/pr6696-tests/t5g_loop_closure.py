#!/usr/bin/env python3
"""T5g · 闭环试验：连续累积 N 步 ×360 units，找「第几步回到起点」

为什么这样能定出 units/度（且不需要角度尺子）：
    每步推进 360 units，累计转角 = 360 × N / (units/度)
    当它等于 360° 时，画面回到起点。设此时步数为 N*，则
        units/度 = N*
    例如 N*=4 → 4 units/度；N*=2 → 2 units/度；N*=8 → 8 units/度。

前提：pointer lock。未锁定时 clientX 超过视口（1280）会被丢弃，无法累积。
      本脚本用 Runtime.evaluate(userGesture=true) 主动请求 video 的指针锁。

判据：画面中部平均像素差。找最小的 N>0 使 diff(F0, Fn) 落到噪声量级。
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import statistics
import sys
import time

import cv2
import numpy as np

import _common as c
import arrow_ruler as ruler

ANCHOR_X, Y = 640, 360
VIEW_ROI = (160, 560, 200, 1100)


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle

    def eval(self, expression: str, gesture: bool = False):
        return self.cdp.eval_json(expression)

    def lock(self) -> bool:
        self.cdp.call("Runtime.evaluate",
                      expression="(() => { const el = document.querySelector('video');"
                                 " if (!el || !el.requestPointerLock) return 'no-el';"
                                 " el.requestPointerLock(); return 'requested'; })()",
                      returnByValue=True, userGesture=True, awaitPromise=True)
        time.sleep(0.6)
        return bool(self.eval("!!document.pointerLockElement"))

    def unlock(self) -> None:
        self.cdp.call("Runtime.evaluate",
                      expression="document.exitPointerLock && document.exitPointerLock()",
                      returnByValue=True)

    def dispatch(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=Y,
                      button="none", buttons=0)

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
    parser = argparse.ArgumentParser(description="T5g 闭环试验")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--units", type=int, default=360, help="每步推进的 units")
    parser.add_argument("--settle", type=float, default=1.2)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    evidence = c.Evidence("t5g", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, args.settle)

    if not probe.lock():
        print("无法进入 pointer lock，试验中止")
        return 2
    print("pointer lock：已获得")

    # 落稳 + 噪声基线
    probe.dispatch(ANCHOR_X)
    time.sleep(0.3)
    probe.dispatch(ANCHOR_X)
    time.sleep(args.settle)
    base = probe.frame()
    idle = []
    prev = base
    for _ in range(3):
        time.sleep(args.settle)
        cur = probe.frame()
        idle.append(diff(prev, cur))
        prev = cur
    noise = statistics.median(idle)
    print(f"噪声基线 {noise:.2f}  样本 {[round(v, 1) for v in idle]}")
    print(f"起始箭头（rot，仅参考）：{ruler.angle_of_frame(base):.1f}°")

    rows = []
    frames = [base]
    for step in range(1, args.steps + 1):
        x = ANCHOR_X + args.units * step
        probe.dispatch(x)
        time.sleep(args.settle)
        frame = probe.frame()
        frames.append(frame)
        to_start = diff(base, frame)
        to_prev = diff(frames[-2], frame)
        angle = ruler.angle_of_frame(frame)
        rows.append({"step": step, "client_x": x,
                     "diff_to_start": round(to_start, 2),
                     "ratio_to_start": round(to_start / noise, 2) if noise else None,
                     "diff_to_prev": round(to_prev, 2),
                     "rot": round(angle, 1)})
        print(f"  第{step}步 x={x:5d}  与起点差 {to_start:6.2f} ({to_start / noise:5.2f}×噪声)"
              f"  与上一步差 {to_prev:6.2f}  rot {angle:6.1f}°")

    # 判读：找最小 N 使差回落到噪声量级
    loop = None
    for row in rows:
        if row["ratio_to_start"] is not None and row["ratio_to_start"] < 2.5:
            loop = row["step"]
            break

    print("\n判读")
    if loop is None:
        print(f"  {args.steps} 步内没有回到起点（最小比值 "
              f"{min(r['ratio_to_start'] for r in rows):.2f}× 噪声）")
        print("  → 可能每步转角过小，或角色/镜头未按 movementX 转动")
    else:
        units_per_degree = loop * args.units / 360.0
        print(f"  第 {loop} 步回到起点 → 每步 ≈ {360 / loop:.1f}° → "
              f"**{units_per_degree:.2f} units/度**（4 单位/度的名义值是 4.00）")
        for step in range(loop, args.steps + 1, loop):
            if step - 1 < len(rows):
                print(f"  校验：第 {step} 步也应回到起点，实测 "
                      f"{rows[step - 1]['ratio_to_start']:.2f}× 噪声")

    probe.unlock()
    print("\npointer lock 已释放")
    evidence.write_json("summary.json", {"noise": round(noise, 2), "rows": rows,
                                         "loop_step": loop, "units": args.units})
    return 0


if __name__ == "__main__":
    sys.exit(main())
