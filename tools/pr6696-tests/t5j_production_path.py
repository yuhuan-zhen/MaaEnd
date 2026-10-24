#!/usr/bin/env python3
"""T5j · 补测：Go 改成 4 单位/度后，生产路径能不能转出 90°

生产路径（cdp_controller.relative_move）与 T5i 的探针发法**不一样**：

    生产：每次都在固定锚点 (640,360) 派发 mouseMoved，靠页内 policy 覆写 movementX
    探针：把指针从 640 推到 640+dx，靠真实位置差

两种发法在客户端眼里是否等价，从来没人验证过。本脚本就是补这一环。

测量仍用「走一步」法（T5i）：
    同步走 → 转镜头 → 再走一步 → Δrot = 镜头转角

模式：
    prod   = 生产发法（固定锚点 + 覆写），按 127 拆段，总量由 --units 给定
    pos    = 探针发法（位置推进），同样总量
    prod1  = 生产发法但用旧灵敏度（总量 ×0.5），对照「改之前会转多少」
"""

from __future__ import annotations

import argparse
import base64
import pathlib
import re
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
MAX_STEP = 127
DEFAULT_CONTROLLER = "/mnt/d/桌面/常用/面向MMAEND项目/MaaEnd-src/tools/cloud-web-linux/cdp_controller.py"


def load_policy_js(path: str) -> str:
    """从控制器源码里取出页内注入的 INPUT_POLICY_JS，保证与生产完全一致。"""
    text = pathlib.Path(path).read_text(encoding="utf-8")
    match = re.search(r'INPUT_POLICY_JS = r"""(.*?)"""', text, re.S)
    if not match:
        raise SystemExit(f"未能在 {path} 里找到 INPUT_POLICY_JS")
    return match.group(1)


class Probe:
    def __init__(self, port: int, settle: float, policy: str) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle
        self.policy = policy

    def ensure_policy(self) -> bool:
        if self.cdp.eval_json("typeof window.__maaCloudRelativeMove") == "function":
            return True
        self.cdp.call("Runtime.evaluate", expression=self.policy, returnByValue=True)
        return self.cdp.eval_json("typeof window.__maaCloudRelativeMove") == "function"

    def mouse(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=Y, button="none", buttons=0)

    def key(self, down: bool) -> None:
        params = {"type": "keyDown" if down else "keyUp", "windowsVirtualKeyCode": VK_W,
                  "nativeVirtualKeyCode": VK_W, "code": "KeyW", "key": "w"}
        if down:
            params["text"] = "w"
        self.cdp.call("Input.dispatchKeyEvent", **params)

    def walk(self, ms: int, pulses: int) -> None:
        for _ in range(pulses):
            self.key(True)
            time.sleep(ms / 1000.0)
            self.key(False)
            time.sleep(0.45)

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

    def reset(self) -> None:
        self.mouse(ANCHOR)
        time.sleep(0.3)
        self.mouse(ANCHOR)
        time.sleep(self.settle)

    def turn_prod(self, units: int) -> list[int]:
        """生产发法：固定锚点 + 覆写 movementX，按 127 拆段（复制 relative_move 的循环）。"""
        steps: list[int] = []
        left = units
        while left:
            step = max(-MAX_STEP, min(MAX_STEP, left))
            self.cdp.call("Runtime.evaluate",
                          expression=f"__maaCloudRelativeMove({step}, 0, {ANCHOR}, {Y})",
                          returnByValue=True)
            self.mouse(ANCHOR)
            steps.append(step)
            left -= step
            time.sleep(0.05)
        return steps

    def turn_pos(self, units: int, pieces: int = 1) -> list[int]:
        """探针发法：真实推进指针位置，按 pieces 分段。"""
        steps: list[int] = []
        for index in range(pieces):
            target = round(units * (index + 1) / pieces)
            self.mouse(ANCHOR + target)
            steps.append(target - (steps[-1] if steps else 0))
            time.sleep(0.06)
        return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="T5j 生产路径转角补测")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--units", type=int, default=360, help="90° 命令在 4 单位/度下应发 360 units")
    parser.add_argument("--modes", default="prod1,prod,pos")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--walk-ms", type=int, default=350)
    parser.add_argument("--walk-pulses", type=int, default=3)
    parser.add_argument("--settle", type=float, default=1.3)
    parser.add_argument("--controller", default=DEFAULT_CONTROLLER)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    policy = load_policy_js(args.controller)
    evidence = c.Evidence("t5j", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, args.settle, policy)
    if not probe.ensure_policy():
        print("页内 policy 注入失败，终止")
        return 2
    print("页内 policy：已就绪（与生产同一份 INPUT_POLICY_JS）")

    rows: list[dict] = []
    for mode in args.modes.split(","):
        units = round(args.units * 0.5) if mode == "prod1" else args.units
        expect = units / 4.0
        print(f"\n== {mode}  units={units}  名义 {expect:.1f}° ==")
        for run in range(1, args.repeat + 1):
            probe.reset()
            probe.walk(args.walk_ms, args.walk_pulses)
            a0 = probe.rot()
            if a0 < 0:
                print("  起始读不出，跳过")
                continue
            if mode == "pos":
                steps = probe.turn_pos(units, pieces=3)
            else:
                steps = probe.turn_prod(units)
            time.sleep(args.settle)
            probe.walk(args.walk_ms, args.walk_pulses)
            a1 = probe.rot()
            if a1 < 0:
                print("  结束读不出，跳过")
                continue
            delta = ruler.circular_delta(a0, a1)
            rows.append({"mode": mode, "units": units, "run": run, "steps": steps,
                         "a0": round(a0, 1), "a1": round(a1, 1), "delta": round(delta, 1)})
            print(f"  run={run}  steps={steps}  rot {a0:6.1f}° → {a1:6.1f}°   Δ {delta:+7.1f}°"
                  f"  （名义 {expect:.1f}°）")

    print("\n汇总（每模式中位）")
    print("  mode   units  名义(°)  Δ中位(°)  达成率")
    summary = []
    for mode in args.modes.split(","):
        subset = [r for r in rows if r["mode"] == mode]
        if not subset:
            continue
        median = statistics.median([abs(r["delta"]) for r in subset])
        expect = subset[0]["units"] / 4.0
        rate = median / expect * 100 if expect else 0
        summary.append({"mode": mode, "units": subset[0]["units"],
                        "expect": round(expect, 1), "median_delta": round(median, 1),
                        "rate": round(rate, 1)})
        print(f"  {mode:6s} {subset[0]['units']:5d}  {expect:7.1f}  {median:8.1f}  {rate:6.1f}%")

    print("\n判读")
    print("  prod ≈ pos   → 生产发法（覆写 movementX + 固定锚点）等价，×4 修正直接生效")
    print("  prod ≈ 0     → 生产发法根本转不动，问题不在灵敏度而在发法本身")
    print("  prod1 ≈ 一半 → 证明改之前 90° 命令只能转 45°")

    evidence.write_json("summary.json", {"rows": rows, "summary": summary,
                                         "policy_len": len(policy)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
