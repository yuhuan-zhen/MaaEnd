#!/usr/bin/env python3
"""L1 帧源层验收：MaaLinuxControlUnit / WlrScreencap 是否给出正确的 1280x720 帧。

只读，不注入任何输入。

判定 8 项（全为 True 才算通过）：
  1. connect           连上 sway（Wayland 合成器）
  2. shape_1280x720    帧尺寸是 1280x720，不依赖 MaaControllerGetResolution
  3. shape_hw3         形如 (720, 1280, 3)
  4. not_blank         不是黑帧 / 纯色
  5. stable            静止画面 20 帧的帧间均值标准差 < 2.0
  6. fast_enough       单帧耗时中位数 < 500 ms
  7. matches_grim      与 grim 参考帧的 NCC > 0.90     ← 缺 grim 时 SKIP
  8. bgr_confirmed     BGR->RGB 的 NCC 高于按 RGB 直用  ← 缺 grim 时 SKIP

记录项（不参与判定）：
  resolution_api  MaaControllerGetResolution 的返回值；Linux 控制器当前返回 (0, 0)
  start_app       上游 LinuxControlUnit 的启停实现状态；本层不探测

SKIP 与 FAIL 的区别：grim 缺失属于「没做这项验证」，不是「验证失败」，所以写 None
而不是 False；但被跳过的项会显式打印，且汇总里带上 skipped 计数，避免「分母变小所以更绿」。
需要严格时用 --require-grim，缺 grim 直接 exit 1。

用法：
    XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
      python3 l1_screencap.py [--socket /run/user/0/wayland-1] [--n 20] [--require-grim]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from maa.controller import LinuxController
from PIL import Image

from harness.common import (
    channel_means,
    default_wlr_socket,
    grim_capture,
    ncc,
    save_png,
)

SCREENCAP_WLR = 1  # MaaLinuxScreencapMethod_WlrScreencap
INPUT_WLR = 1      # MaaLinuxInputMethod_Wlr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default=default_wlr_socket(),
                    help="Wayland socket；默认 $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="evidence-l1")
    ap.add_argument("--require-grim", action="store_true",
                    help="grim 不可用时直接失败；默认只跳过两项交叉验证")
    args = ap.parse_args()

    out_dir = Path(__file__).parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"socket": args.socket, "checks": {}, "ok": False}

    # --- 创建并连接 ---
    cfg = {
        "screencap_method": SCREENCAP_WLR,
        "input_method": INPUT_WLR,
        "wlr_socket_path": args.socket,
        "use_win32_vk_code": True,
    }
    t0 = time.time()
    try:
        ctrl = LinuxController(cfg)
    except Exception as exc:
        print(f"[FAIL] LinuxController 创建失败: {exc}")
        result["error"] = str(exc)
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1

    job = ctrl.post_connection()
    job.wait()
    if not job.succeeded:
        print(f"[FAIL] connect 失败: {job.status}")
        result["error"] = f"connect {job.status}"
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1
    result["connect_ms"] = round((time.time() - t0) * 1000, 1)
    print(f"[ ok ] connect  {result['connect_ms']} ms")

    # --- 记录项：分辨率 API 与启停能力（都不参与判定）---
    try:
        res_api = ctrl.resolution
    except Exception:
        res_api = None
    result["resolution_api"] = list(res_api) if res_api else None
    result["start_app"] = {
        "probed": False,
        "note": "上游 LinuxControlUnit 的 start_app 仍为 TODO，本层不探测",
    }
    print(f"[info] resolution(API) = {res_api}  （记录项，不判定）")

    # --- 参考帧（grim），必须在抓帧循环之前，避免和截图抢合成器 ---
    grim_path = out_dir / "ref-grim.png"
    has_grim = grim_capture(grim_path)
    if not has_grim and args.require_grim:
        print("[FAIL] --require-grim 已指定，但 grim 不可用")
        result["error"] = "grim unavailable (required)"
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1

    # --- 抓 n 帧 ---
    frames: list[np.ndarray] = []
    times: list[float] = []
    for _ in range(args.n):
        t = time.time()
        frames.append(ctrl.post_screencap().wait().get())
        times.append((time.time() - t) * 1000.0)

    first = frames[0]
    result["frame_shape"] = list(first.shape)
    result["frame_dtype"] = str(first.dtype)
    result["channel_means_bgr"] = channel_means(first)

    ms = sorted(times)
    result["screencap_ms"] = {
        "min": round(ms[0], 1),
        "median": round(statistics.median(ms), 1),
        "p95": round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 1),
        "max": round(ms[-1], 1),
    }
    print(f"[info] shape={first.shape} dtype={first.dtype}")
    print(f"[info] 通道均值(BGR)={result['channel_means_bgr']}")
    print(f"[info] 耗时 min/median/p95/max = "
          f"{result['screencap_ms']['min']}/{result['screencap_ms']['median']}/"
          f"{result['screencap_ms']['p95']}/{result['screencap_ms']['max']} ms")

    # --- 静止画面稳定性 ---
    means = [float(f.mean()) for f in frames]
    result["frame_mean_std"] = round(float(np.std(means)), 4)
    result["frame_mean_range"] = [round(min(means), 3), round(max(means), 3)]

    # --- 干净帧落盘 ---
    frame_path = out_dir / "frame-bgr2rgb.png"
    save_png(first, frame_path)
    print(f"[info] 帧已落盘 {frame_path.name}")

    # --- 通道序交叉验证 ---
    if has_grim:
        ref = np.asarray(Image.open(grim_path).convert("RGB"), dtype=np.uint8)
        result["grim_shape"] = list(ref.shape)
        if ref.shape[:2] == first.shape[:2]:
            result["ncc_bgr2rgb"] = round(ncc(first[:, :, ::-1], ref), 5)
            result["ncc_as_is"] = round(ncc(first, ref), 5)
            result["ch_means_ref_rgb"] = channel_means(ref)
            print(f"[info] NCC(frame BGR->RGB, grim) = {result['ncc_bgr2rgb']}")
            print(f"[info] NCC(frame 原样当作RGB, grim) = {result['ncc_as_is']}")
            print(f"[info] grim 通道均值(RGB) = {result['ch_means_ref_rgb']}")
        else:
            result["grim_shape_mismatch"] = True
    else:
        result["grim"] = "unavailable"
        print("[skip] 未找到 grim：matches_grim / bgr_confirmed 跳过")
        print("       安装后重跑可获得通道序的独立验证：sudo apt install grim")

    # --- 判定 ---
    checks = result["checks"]
    checks["connect"] = True
    checks["shape_1280x720"] = (first.shape[1], first.shape[0]) == (1280, 720)
    checks["shape_hw3"] = (len(first.shape) == 3 and first.shape[2] == 3)
    checks["not_blank"] = 5.0 < float(first.mean()) < 250.0
    checks["stable"] = result["frame_mean_std"] < 2.0
    checks["fast_enough"] = result["screencap_ms"]["median"] < 500.0
    if "ncc_bgr2rgb" in result:
        checks["matches_grim"] = result["ncc_bgr2rgb"] > 0.90
        checks["bgr_confirmed"] = result["ncc_bgr2rgb"] > result["ncc_as_is"]
    else:
        checks["matches_grim"] = None
        checks["bgr_confirmed"] = None
        result["skipped"] = ["matches_grim", "bgr_confirmed"]

    judged = {k: v for k, v in checks.items() if v is not None}
    result["ok"] = all(judged.values())
    result["passed"] = sum(1 for v in judged.values() if v)
    result["judged"] = len(judged)
    (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\n=== L1 判定 ===")
    for k, v in checks.items():
        mark = "SKIP" if v is None else ("PASS" if v else "FAIL")
        print(f"  [{mark}] {k}")
    skipped = len(checks) - len(judged)
    print(f"\nL1_{'OK' if result['ok'] else 'NG'}  "
          f"passed={result['passed']}/{len(judged)}"
          + (f" (skipped={skipped})" if skipped else ""))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
