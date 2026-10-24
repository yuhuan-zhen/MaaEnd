#!/usr/bin/env python3
"""T5d · 绝对标定 + 时间维度：回答「大位移是被完整消费，还是被速率上限吃掉了」

三组子实验：

A. 线性标定（px/unit）
   小角度下画面平移量近似与转角成正比。用 dx=20..140 测「平移像素/单位」，
   检验是否线性；线性成立 → 小段投递没有丢，可作为后续参照。

B. 等量不同发法（0 ms 间隔 vs 300 ms 间隔）
   T=360 三种发法：①一次发完 ②拆 3×120 快速连续 ③拆 3×120 每段间隔 300ms
   若 ② ≈ ① 但 ③ ≠ ①  → 说明瓶颈是**每帧/每秒速率**，不是单事件幅度（这会推翻 T5c 的结论）
   若 ③ ≈ ② ≈ ①        → 时间维度无影响

C. 回位残差
   +T 后回 −T，残差应≈噪声。残差随 T 增大说明有丢步或惯性；与 B 合看可区分。

判据统一用「画面中部平均像素差」，与同场噪声基线比较。

用法：
    python3 t5d_absolute_and_pacing.py --port 9334
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

ANCHOR = (640, 360)
VIEW_ROI = (160, 560, 200, 1100)


class Probe:
    def __init__(self, port: int, settle: float) -> None:
        self.cdp = c.Cdp(c.page_target(port, "endfield"))
        self.settle = settle

    def dispatch(self, x: int) -> None:
        self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=ANCHOR[1],
                      button="none", buttons=0)

    def reset(self) -> None:
        self.dispatch(ANCHOR[0])
        time.sleep(0.25)
        self.dispatch(ANCHOR[0])
        time.sleep(self.settle)

    def send(self, total: int, pieces: int = 1, gap: float = 0.0) -> None:
        for index in range(pieces):
            target = round(total * (index + 1) / pieces)
            self.dispatch(ANCHOR[0] + target)
            if gap and index + 1 < pieces:
                time.sleep(gap)

    def back(self) -> None:
        self.dispatch(ANCHOR[0])

    def frame(self) -> np.ndarray:
        data = self.cdp.call("Page.captureScreenshot", format="png")["data"]
        raw = base64.b64decode(data.split(",", 1)[1] if "," in data else data)
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def view(frame: np.ndarray) -> np.ndarray:
    y1, y2, x1, x2 = VIEW_ROI
    return frame[y1:y2, x1:x2]


def mean_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(view(a).astype(np.int16) - view(b).astype(np.int16)).mean())


def shift_px(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    ga = np.float32(cv2.cvtColor(view(a), cv2.COLOR_BGR2GRAY))
    gb = np.float32(cv2.cvtColor(view(b), cv2.COLOR_BGR2GRAY))
    (dx, dy), response = cv2.phaseCorrelate(ga, gb)
    return float(dx), float(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="T5d 绝对标定与时间维度")
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--settle", type=float, default=1.0)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--out", default="evidence")
    args = parser.parse_args()

    evidence = c.Evidence("t5d", pathlib.Path(args.out))
    log_path = pathlib.Path(evidence.path()) / "run.log"
    log_file = log_path.open("w", encoding="utf-8")

    def say(text: str) -> None:
        print(text)
        log_file.write(text + "\n")
        log_file.flush()

    say(f"证据目录：{pathlib.Path(evidence.path()).resolve()}")
    probe = Probe(args.port, args.settle)
    result: dict = {}

    # ---------- 噪声基线 ----------
    probe.reset()
    idle = []
    prev = probe.frame()
    for _ in range(5):
        time.sleep(args.settle)
        cur = probe.frame()
        idle.append(mean_diff(prev, cur))
        prev = cur
    noise = statistics.median(idle)
    result["noise"] = {"samples": [round(v, 2) for v in idle], "median": round(noise, 2)}
    say(f"[基线] 静止帧间差 中位 {noise:.2f}  样本 {[round(v, 1) for v in idle]}")

    # ---------- A. 线性标定 ----------
    say("\n[A] 线性标定：dx → 画面平移像素")
    ladder = [20, 40, 60, 80, 100, 120, 140]
    a_rows = []
    for dx in ladder:
        for run in range(1, args.repeat + 1):
            probe.reset()
            base = probe.frame()
            probe.send(dx)
            time.sleep(args.settle)
            moved = probe.frame()
            shift, response = shift_px(base, moved)
            a_rows.append({"dx": dx, "run": run, "shift": round(shift, 2),
                           "response": round(response, 3),
                           "diff": round(mean_diff(base, moved), 2)})
            say(f"  dx={dx:3d} run={run}: 平移 {shift:+8.2f}px  响应 {response:.3f}  画面差 {mean_diff(base, moved):5.2f}")
            probe.back()
            time.sleep(args.settle)
    result["A_ladder"] = a_rows

    medians = {}
    for dx in ladder:
        values = [abs(r["shift"]) for r in a_rows if r["dx"] == dx]
        if values:
            medians[dx] = statistics.median(values)
    say("\n  dx   |平移| 中位   每单位(px)   相对 dx=20")
    per_unit_reference = None
    for dx in ladder:
        if dx not in medians:
            continue
        per_unit = medians[dx] / dx
        if dx == ladder[0]:
            per_unit_reference = per_unit
        ratio = per_unit / per_unit_reference if per_unit_reference else float("nan")
        say(f"  {dx:3d}  {medians[dx]:8.2f}  {per_unit:9.4f}   {ratio:6.3f}")
    result["A_per_unit"] = {dx: round(medians[dx] / dx, 4) for dx in medians}

    # ---------- B. 等量不同发法 ----------
    say("\n[B] T=360 三种发法（一次 / 3×120 连发 / 3×120 间隔 300ms）")
    b_rows = []
    conditions = [
        ("single", 360, 1, 0.0),
        ("split_fast", 360, 3, 0.0),
        ("split_slow", 360, 3, 0.30),
    ]
    frames: dict[str, list[np.ndarray]] = {name: [] for name, *_ in conditions}
    for run in range(1, args.repeat + 1):
        for name, total, pieces, gap in conditions:
            probe.reset()
            base = probe.frame()
            probe.send(total, pieces=pieces, gap=gap)
            time.sleep(args.settle)
            final = probe.frame()
            frames[name].append(final)
            b_rows.append({"run": run, "cond": name, "diff_vs_base": round(mean_diff(base, final), 2)})
            say(f"  run={run} {name:11s}: 动后差 {mean_diff(base, final):5.2f}")
            probe.back()
            time.sleep(args.settle)

    say("\n  条件间差异（越小说明最终朝向越一致）")
    pairs = [("single", "split_fast"), ("single", "split_slow"), ("split_fast", "split_slow")]
    b_pairs = []
    for left, right in pairs:
        values = [mean_diff(frames[left][i], frames[right][i])
                  for i in range(min(len(frames[left]), len(frames[right])))]
        if not values:
            continue
        median = statistics.median(values)
        b_pairs.append({"pair": f"{left} vs {right}", "median_diff": round(median, 2),
                        "ratio_to_noise": round(median / noise, 2) if noise else None})
        say(f"  {left:11s} vs {right:11s}: {median:6.2f}  = {median / noise:5.2f}× 噪声")
    result["B_pairs"] = b_pairs
    result["B_rows"] = b_rows

    # ---------- C. 回位残差 ----------
    say("\n[C] 回位残差（+T 再 −T，应回到起点）")
    c_rows = []
    for total in (120, 200, 360):
        for run in range(1, args.repeat + 1):
            probe.reset()
            base = probe.frame()
            probe.send(total)
            time.sleep(args.settle)
            probe.back()
            time.sleep(args.settle)
            home = probe.frame()
            residual = mean_diff(base, home)
            c_rows.append({"total": total, "run": run, "residual": round(residual, 2),
                           "ratio_to_noise": round(residual / noise, 2) if noise else None})
            say(f"  T={total:3d} run={run}: 残差 {residual:5.2f}  = {residual / noise:5.2f}× 噪声")
    result["C_residual"] = c_rows

    # ---------- 结论 ----------
    say("\n[判读]")
    slopes = [medians[dx] / dx for dx in ladder if dx in medians]
    if slopes:
        spread = max(slopes) / min(slopes) if min(slopes) else float("inf")
        say(f"  A: 每单位平移量在 {min(slopes):.3f}–{max(slopes):.3f} px 之间（极差 {spread:.2f}×）")
        say(f"     {'线性（投递无丢失）' if spread < 1.35 else '非线性 → 某些档位被削弱，需要追查'}")
    fast = next((row["ratio_to_noise"] for row in b_pairs if row["pair"] == "single vs split_fast"), None)
    slow = next((row["ratio_to_noise"] for row in b_pairs if row["pair"] == "single vs split_slow"), None)
    if fast is not None and slow is not None:
        say(f"  B: 一次 vs 连发 {fast:.2f}× 噪声；一次 vs 慢速拆发 {slow:.2f}× 噪声")
        if fast < 3 <= slow:
            say("     → 慢速拆发与一次发不一致：瓶颈是**速率**，T5c 的结论需修正")
        else:
            say("     → 时间维度未造成差异：单事件幅度上限未观察到")
    residuals = [row["residual"] for row in c_rows]
    if residuals:
        say(f"  C: 回位残差 {min(residuals):.1f}–{max(residuals):.1f}（噪声 {noise:.1f}）")

    evidence.write_json("summary.json", result)
    say(f"\n日志：{log_path}")
    log_file.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
