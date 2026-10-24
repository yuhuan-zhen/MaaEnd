#!/usr/bin/env python3
"""T5f · 连续 8 次 +360 units，看朝向累计是否符合预期（闭环试验）

为什么这样设计：
    如果 4 units/度，每次 360 → +90°，累计 90/180/270/360/450/540/630/720
        → 第 4 次回到起点，第 8 次再回起点（两圈）
    如果 2 units/度，每次 360 → +180°
        → 第 2 次回到起点（每两次一圈）
    所以「第几次回到起点」直接给出 units/度，不需要知道 FOV。

指针推进方式：
    每次把 clientX 再推进 360（640 → 1000 → 1360 …）。
    若浏览器把 clientX 夹在视口内但仍按差值算 movementX，就能连续累积；
    若被夹断（movementX < 360），脚本会检测到并报告，改用回位式采样。

角度尺子：arrow_ruler.py（MaaEnd InferYellowArrowRotation 移植，已验证 1.41° 中位误差）
注意：读的是 rot（角色朝向）。若该状态下角色不跟随镜头，本试验不成立——脚本会用首步做自检。
"""
from __future__ import annotations

import argparse
import base64
import pathlib
import sys
import time

import cv2
import numpy as np

import _common as c
import arrow_ruler as ruler

ANCHOR_X, Y = 640, 360
STEP = 360
STEPS = 8

RECORDER = """
(() => {
  window.__t5f = [];
  for (const t of ['mousemove','pointermove']) {
    window.addEventListener(t, (e) => {
      window.__t5f.push({t: t, mx: e.movementX | 0, my: e.movementY | 0,
                         x: e.clientX, y: e.clientY, trusted: e.isTrusted});
    }, {capture: true, passive: true});
  }
  return 'ok';
})()
"""


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle
        self.cdp.call("Runtime.evaluate", expression=RECORDER, returnByValue=True)

    def dispatch(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=Y,
                      button="none", buttons=0)

    def frame(self) -> np.ndarray:
        data = self.cdp.call("Page.captureScreenshot", format="png")["data"]
        raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def angle(self, tries: int = 3) -> float:
        for _ in range(tries):
            value = ruler.angle_of_frame(self.frame())
            if value >= 0:
                return value
            time.sleep(0.2)
        return -1.0

    def reset(self) -> None:
        """回到锚点并稳定（第二次原地发，delta=0）。"""
        self.dispatch(ANCHOR_X)
        time.sleep(0.25)
        self.dispatch(ANCHOR_X)
        time.sleep(self.settle)
        self.cdp.call("Runtime.evaluate", expression="window.__t5f = []", returnByValue=True)

    def received(self) -> list[int]:
        log = self.cdp.eval_json("window.__t5f") or []
        self.cdp.call("Runtime.evaluate", expression="window.__t5f = []", returnByValue=True)
        return [e["mx"] for e in log if e["t"] == "mousemove"]


def main() -> int:
    parser = argparse.ArgumentParser(description="T5f 连续 8 次 90° 闭环试验")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--steps", type=int, default=STEPS)
    parser.add_argument("--step", type=int, default=STEP, help="每次推进的 units")
    parser.add_argument("--settle", type=float, default=1.0)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    evidence = c.Evidence("t5f", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, args.settle)

    probe.reset()
    start = probe.angle()
    print(f"起始朝向：{start:.1f}°" if start >= 0 else "起始朝向读不出")
    if start < 0:
        return 2

    rows = []
    angles = [start]
    x = ANCHOR_X
    for step in range(1, args.steps + 1):
        x += args.step
        probe.dispatch(x)
        time.sleep(args.settle)
        received = probe.received()
        angle = probe.angle()
        delta = ruler.circular_delta(angles[-1], angle) if angle >= 0 else float("nan")
        cumulative = (angle - start) % 360 if angle >= 0 else float("nan")
        rows.append({"step": step, "client_x": x, "received": received,
                     "angle": None if angle < 0 else round(angle, 1),
                     "delta": None if delta != delta else round(delta, 1),
                     "cumulative_mod360": None if cumulative != cumulative else round(cumulative, 1)})
        if angle >= 0:
            angles.append(angle)
        print(f"  第{step}步 clientX={x:5d} 收到 {received}  "
              f"角度 {angle:6.1f}°  Δ {delta:+7.1f}°  累计(模360) {cumulative:6.1f}°")

    # 回到锚点（会反向转回去，这里只验证能否复位）
    probe.dispatch(ANCHOR_X)
    time.sleep(args.settle)
    home = probe.angle()
    print(f"\n回位后：{home:.1f}°  与起始差 {ruler.circular_delta(start, home):+.1f}°")

    # 判读
    print("\n判读（看「第几步回到起点」）")
    if len(angles) > 1:
        for index, angle in enumerate(angles[1:], start=1):
            gap = abs(ruler.circular_delta(start, angle))
            if gap < 8.0:
                print(f"  第 {index} 步回到起点附近（差 {gap:.1f}°）→ 每次 ≈ {360 / index:.1f}°")
                break
        else:
            print("  8 步内没有回到起点 —— 可能角色不跟镜头，或每次转角远小于 90°")

    evidence.write_json("summary.json", {"start": start, "rows": rows, "home": home})
    return 0


if __name__ == "__main__":
    sys.exit(main())
