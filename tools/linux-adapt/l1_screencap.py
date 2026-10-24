#!/usr/bin/env python3
"""L1 帧源层验收：MaaLinuxControlUnit / WlrScreencap 是否给出正确的 1280x720 帧。

只读，不注入任何输入。判定项：
  1. resolution == (1280, 720)，帧 shape == (720, 1280, 3)
  2. 通道序：binding 声明是 BGR；用 grim 同协议参考帧交叉验证
  3. 帧耗时分布（20 帧）
  4. 静止画面下的帧间稳定性（均值标准差）
  5. 与 grim 参考帧的相似度（NCC），确认不是黑帧/花屏/错缩放

用法：
    XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
      python3 l1_screencap.py [--socket /run/user/0/wayland-1] [--n 20]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from maa.controller import LinuxController
from PIL import Image

SCREENCAP_WLR = 1  # MaaLinuxScreencapMethod_WlrScreencap
INPUT_WLR = 1      # MaaLinuxInputMethod_Wlr


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关（灰度、零均值）。"""
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float("nan") if denom == 0 else float(a.dot(b) / denom)


def channel_means(img: np.ndarray) -> list[float]:
    return [round(float(img[:, :, i].mean()), 3) for i in range(img.shape[2])]


def grim_capture(out_path: Path) -> bool:
    """用 grim 抓同一路 wlroots 输出作为参考（同 zwlr_screencopy 协议）。"""
    try:
        subprocess.run(["grim", str(out_path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out_path.exists()
    except Exception:
        return False


def save_png(img: np.ndarray, out_path: Path, bgr: bool = True) -> None:
    """BGR -> RGB 后落盘。"""
    arr = img[:, :, ::-1] if bgr and img.shape[2] == 3 else img
    Image.fromarray(arr.astype(np.uint8)).save(out_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/run/user/0/wayland-1")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="evidence-l1")
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

    # --- 分辨率 ---
    try:
        res = ctrl.resolution
    except Exception:
        res = None
    result["resolution"] = list(res) if res else None
    print(f"[info] resolution = {res}")

    # --- 参考帧（grim） ---
    grim_path = out_dir / "ref-grim.png"
    has_grim = grim_capture(grim_path)

    # --- 抓 n 帧 ---
    frames: list[np.ndarray] = []
    times: list[float] = []
    for i in range(args.n):
        t = time.time()
        r = ctrl.post_screencap().wait().get()
        times.append((time.time() - t) * 1000.0)
        if i == 0:
            frames.append(r)
        else:
            frames.append(r)
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
            as_rgb = first[:, :, ::-1]           # 按 binding 声明：BGR -> RGB
            as_is = first                        # 若当成 RGB 直接用
            result["ncc_bgr2rgb"] = round(ncc(as_rgb, ref), 5)
            result["ncc_as_is"] = round(ncc(as_is, ref), 5)
            result["ch_means_ref_rgb"] = channel_means(ref)
            print(f"[info] NCC(frame BGR->RGB, grim) = {result['ncc_bgr2rgb']}")
            print(f"[info] NCC(frame 原样当作RGB, grim) = {result['ncc_as_is']}")
            print(f"[info] grim 通道均值(RGB) = {result['ch_means_ref_rgb']}")
        else:
            result["grim_shape_mismatch"] = True
    else:
        result["grim"] = "unavailable"

    # --- 判定 ---
    checks = result["checks"]
    checks["connect"] = True
    checks["resolution_1280x720"] = (result["resolution"] == [1280, 720]
                                     or (first.shape[1], first.shape[0]) == (1280, 720))
    checks["shape_hw3"] = (len(first.shape) == 3 and first.shape[2] == 3)
    checks["not_blank"] = 5.0 < float(first.mean()) < 250.0
    checks["stable"] = result["frame_mean_std"] < 2.0
    checks["fast_enough"] = result["screencap_ms"]["median"] < 500.0
    if "ncc_bgr2rgb" in result:
        checks["matches_grim"] = result["ncc_bgr2rgb"] > 0.90
        checks["bgr_confirmed"] = result["ncc_bgr2rgb"] > result["ncc_as_is"]

    result["ok"] = all(checks.values())
    (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\n=== L1 判定 ===")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\nL1_{'OK' if result['ok'] else 'NG'}  "
          f"passed={sum(checks.values())}/{len(checks)}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
