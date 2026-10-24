#!/usr/bin/env python3
"""T5b · 在真实云游戏页面上量「一次相对移动转了多少度」

要回答的问题（#6807 的 `relative_move.max_step = 127` 目前没有任何实测来源）：

    单次 movementX 超过 127 时，SDK 是照单全收、截断到 127、还是溢出反向？

三段流程：

  ① 自检（sanity）  发 dx=40（名义 10°），看箭头是否跟着动
       - 动 → 角色跟随镜头，尺子可用，继续
       - 不动 → 角色没跟镜头（战斗中/锁定），中止并报原因。**这不是测量失败，是状态不对**
  ② 扫描（sweep）   对每档 dx 重复 N 次：读角 → 发 dx → 读角 → 发 -dx → 读角
       - 正向变化 Δ1 用于判定；回位后的读数用于检出漂移
  ③ 判定（verdict） 把 Δ1 与三种假设比：

         无截断    Δ ≈ dx / 4        （云网页 4 units/度）
         clamp@127 Δ ≈ 127 / 4 = 31.75°（与 dx 无关）
         wrap@128  Δ 反向（≈ -(dx-256)/4 或明显负值）

测量工具：`arrow_ruler.py`（MaaEnd `InferYellowArrowRotation` 的移植）
          离线已在 86 张带标注图上验证：中位误差 1.41°

用法：
    python3 t5b_turn_measure.py --port 9334
    python3 t5b_turn_measure.py --port 9334 --dx 40,127,128,200,360 --repeat 3
    python3 t5b_turn_measure.py --port 9334 --skip-sanity      # 已知角色跟镜头时

前提：
    - 浏览器已在跑（`--remote-debugging-port`），页面已进入游戏且能看到小地图
    - 角色处于**跟随镜头**的状态（脱战、非锁定）；否则自检会拦下来
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

ANCHOR = (640, 360)
UNITS_PER_DEGREE = 4.0          # 云网页基准（#6807 CloudViewInput.h）

RECORDER_JS = """
(() => {
  window.__t5b = [];
  for (const t of ['mousemove', 'pointermove']) {
    window.addEventListener(t, (e) => {
      window.__t5b.push({t: t, mx: e.movementX | 0, my: e.movementY | 0, trusted: e.isTrusted});
    }, {capture: true, passive: true});
  }
  return 'ok';
})()
"""


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle
        self.cdp.call("Runtime.evaluate", expression=RECORDER_JS, returnByValue=True)

    def frame(self) -> np.ndarray:
        data = self.cdp.call("Page.captureScreenshot", format="png")["data"]
        raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def angle(self, tries: int = 3) -> float:
        """读箭头角度；读不出时短暂等待重试（横幅遮挡会返回 -1）。"""
        for _ in range(tries):
            value = ruler.angle_of_frame(self.frame())
            if value >= 0:
                return value
            time.sleep(0.25)
        return -1.0

    def move(self, x: int, y: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="none", buttons=0)

    def received(self) -> list[dict]:
        log = self.cdp.eval_json("window.__t5b") or []
        self.cdp.call("Runtime.evaluate", expression="window.__t5b = []", returnByValue=True)
        return [e for e in log if e["t"] == "mousemove"]

    def settle_anchor(self) -> None:
        """落到锚点并稳定：第二次原地移动的 movementX 为 0，不干扰读数。"""
        self.move(ANCHOR[0], ANCHOR[1])
        time.sleep(0.25)
        self.move(ANCHOR[0], ANCHOR[1])
        time.sleep(self.settle)
        self.received()


def verdict_line(dx: int, delta: float) -> tuple[str, str]:
    """把一次实测转角映射成结论。"""
    expected_no_clamp = dx / UNITS_PER_DEGREE
    if delta < -5.0:
        return "wrap?", f"Δ 为负（{delta:+.1f}°），疑似 8 位溢出反向"
    if abs(delta - expected_no_clamp) <= max(5.0, expected_no_clamp * 0.12):
        return "无截断", f"Δ≈{expected_no_clamp:.1f}°，与名义一致"
    if dx > 127 and abs(delta - 127.0 / UNITS_PER_DEGREE) <= 6.0:
        return "clamp@127", "Δ≈31.75°，与 127/4 一致"
    if delta < expected_no_clamp * 0.6:
        return "受限于某上限", f"Δ 明显小于名义 {expected_no_clamp:.1f}°"
    return "不确定", "落在判据之间，需要更多样本"


def main() -> int:
    parser = argparse.ArgumentParser(description="T5b 相对移动转角实测")
    parser.add_argument("--port", type=int, default=9334, help="浏览器调试端口")
    parser.add_argument("--dx", default="40,127,128,160,200,254,300,360", help="待测档位")
    parser.add_argument("--repeat", type=int, default=3, help="每档重复次数")
    parser.add_argument("--settle", type=float, default=0.9, help="每次移动后的稳定等待（秒）")
    parser.add_argument("--skip-sanity", action="store_true", help="跳过自检")
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    steps = [int(v) for v in args.dx.split(",")]
    evidence = c.Evidence("t5b", pathlib.Path(args.out))
    print(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")

    probe = Probe(args.port, args.settle)
    result: dict = {"units_per_degree": UNITS_PER_DEGREE, "steps": [], "sanity": None}

    # ① 自检
    probe.settle_anchor()
    if args.skip_sanity:
        print("自检：已跳过")
    else:
        base_angle = probe.angle()
        if base_angle < 0:
            print("自检失败：读不出箭头角度（小地图被遮挡？）")
            return 2
        probe.move(ANCHOR[0] + 40, ANCHOR[1])
        time.sleep(args.settle)
        after = probe.angle()
        probe.move(ANCHOR[0], ANCHOR[1])
        time.sleep(args.settle)
        delta = ruler.circular_delta(base_angle, after) if after >= 0 else float("nan")
        result["sanity"] = {"base": base_angle, "after": after, "delta": delta}
        print(f"自检：基准 {base_angle:.1f}° → 发 dx=40 后 {after:.1f}°  Δ={delta:+.1f}°（名义 10°）")
        if not (delta == delta) or abs(delta) < 2.0:
            print("\n中止：箭头没有跟随镜头。")
            print("  含义：角色当前不跟镜头走（战斗中/锁定/剧情），此时测不到镜头转角。")
            print("  处理：脱战或走两步让角色朝向对齐镜头，然后加 --skip-sanity 重跑。")
            evidence.write_json("summary.json", result)
            return 3

    # ② 扫描
    samples: dict[int, list[dict]] = {}
    for dx in steps:
        samples[dx] = []
        for run in range(1, args.repeat + 1):
            probe.settle_anchor()
            before = probe.angle()
            if before < 0:
                print(f"  dx={dx} run={run}: 起点读不出，跳过")
                continue
            probe.move(ANCHOR[0] + dx, ANCHOR[1])
            time.sleep(args.settle)
            forward_received = probe.received()
            after = probe.angle()
            probe.move(ANCHOR[0], ANCHOR[1])
            time.sleep(args.settle)
            back_received = probe.received()
            home = probe.angle()

            delta = ruler.circular_delta(before, after) if after >= 0 else float("nan")
            drift = ruler.circular_delta(before, home) if home >= 0 else float("nan")
            record = {
                "dx": dx, "run": run,
                "before": round(before, 1), "after": round(after, 1), "home": round(home, 1),
                "delta_deg": None if delta != delta else round(delta, 2),
                "home_drift_deg": None if drift != drift else round(drift, 2),
                "received_forward": [e["mx"] for e in forward_received],
                "received_back": [e["mx"] for e in back_received],
            }
            samples[dx].append(record)
            print(f"  dx={dx:4d} run={run}  前 {before:6.1f}°  后 {after:6.1f}°  "
                  f"Δ={delta:+7.1f}°  回位漂移={drift:+5.1f}°  收到 {record['received_forward']}")

    # ③ 判定
    print("\n档位   名义角度   实测中位   比值   判定")
    print("----  --------  --------  -----  ----------------")
    table = []
    for dx in steps:
        deltas = [s["delta_deg"] for s in samples[dx] if s["delta_deg"] is not None]
        if not deltas:
            table.append({"dx": dx, "verdict": "无数据"})
            print(f"{dx:4d}  {dx / UNITS_PER_DEGREE:8.1f}  {'—':>8}  {'—':>5}  无数据")
            continue
        median = statistics.median(deltas)
        nominal = dx / UNITS_PER_DEGREE
        ratio = median / nominal if nominal else float("nan")
        tag, why = verdict_line(dx, median)
        table.append({"dx": dx, "nominal": nominal, "median_delta": round(median, 2),
                      "ratio": round(ratio, 3), "verdict": tag, "why": why,
                      "samples": deltas})
        print(f"{dx:4d}  {nominal:8.1f}  {median:8.1f}  {ratio:5.2f}  {tag}（{why}）")

    result["steps"] = table
    evidence.write_json("summary.json", result)

    print("\n判读要点")
    print("  1. 若各档比值都 ≈1.00 → 不存在 127 截断，max_step 可以去掉")
    print("  2. 若 dx>127 的档位都停在 ≈31.75° → clamp@127，127 这个值是必要的")
    print("  3. 若出现负 Δ → 8 位溢出反向，max_step 必须严格 <128")
    print("  4. 回位漂移应接近 0；若持续偏大，说明测量环境不稳（镜头惯性/遮挡），该批作废")
    return 0


if __name__ == "__main__":
    sys.exit(main())
