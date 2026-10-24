#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingModuleSource=false  # 讲解副本：依赖（maa/numpy/pillow）不在阅读环境的解释器里，静音导入告警
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

# 让类型注解延迟求值：写 list[np.ndarray] 这类较新语法时，旧解释器也不当场报错。
from __future__ import annotations

# 解析命令行参数，避免把 socket 路径写死在代码里。
import argparse
# 把验收结果写成 JSON，方便事后 diff 与归档。
import json
# 算中位数。只看平均值会被个别慢帧带偏。
import statistics
# 设置进程退出码：0 = 通过，2 = 判定失败。脚本化验收靠退出码判断。
import sys
# 给每一步计时。
import time
# 路径对象比手拼字符串安全。
from pathlib import Path

# 截图在内存里就是「高 × 宽 × 3」的数值矩阵：求均值、点积、翻转通道都要它。
import numpy as np
# LinuxController 是 binding 里代表 Linux 控制器的类。
# 注意：import 名是 maa，安装的 PyPI 包名是 maafw（两者不同）。
from maa.controller import LinuxController
# 读 grim 抓的 PNG。PIL 只认 RGB，所以对比前要转。
from PIL import Image

# 五个共用工具，抽到 harness/common.py（L2 的输入探针也要用，避免各写一份后分叉）：
#   ncc / channel_means / save_png / grim_capture / default_wlr_socket
# 以脚本方式运行时 sys.path[0] 就是本目录，所以 harness 能被直接导入。
from harness.common import (
    channel_means,
    default_wlr_socket,
    grim_capture,
    ncc,
    save_png,
)

# 截图方式：1 = WlrScreencap（FW-2.4 的 Linux Screencap 表）。
SCREENCAP_WLR = 1  # MaaLinuxScreencapMethod_WlrScreencap
# 输入方式：1 = Wlr。本层不做输入，但创建控制器时必填。
INPUT_WLR = 1      # MaaLinuxInputMethod_Wlr



# ---------------------------------------------------------------------------
# 入口：连接 → 记录项 → grim 参考帧 → 抓帧 → 量四项 → 对账 → 判定
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
# default_wlr_socket() 从 $XDG_RUNTIME_DIR + $WAYLAND_DISPLAY 推导，
# 换用户/换发行版不用改代码；命令行仍可覆盖。
    ap.add_argument("--socket", default=default_wlr_socket(),
                    help="Wayland socket；默认 $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="evidence-l1")
# 严格模式开关：默认缺 grim 只跳过两项，加上这个才把它当失败。
# 用途：想「必须验到通道序」的场合（比如出交付证据），别让环境缺工具悄悄降低覆盖面。
    ap.add_argument("--require-grim", action="store_true",
                    help="grim 不可用时直接失败；默认只跳过两项交叉验证")
    args = ap.parse_args()

# 证据默认落在 tools/linux-adapt/evidence-l1/（.gitignore 已排除 evidence-*/）。
    out_dir = Path(__file__).parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"socket": args.socket, "checks": {}, "ok": False}

    # --- 创建并连接 ---
# 直接对应 MaaLinuxControllerCreate 的 config_json：
#   use_win32_vk_code=true 表示键盘按 Win32 VK 解释 —— MaaEnd 的 pipeline 全都按 VK 写，
#   若用默认的 evdev 扫描码，27(ESC) 会变成另一个键：pipeline 全对而按键全错。
    cfg = {
        "screencap_method": SCREENCAP_WLR,
        "input_method": INPUT_WLR,
        "wlr_socket_path": args.socket,
        "use_win32_vk_code": True,
    }
    t0 = time.time()
    try:
# 构造失败要给非 0 退出码并落盘，不能静默返回。
        ctrl = LinuxController(cfg)
    except Exception as exc:
        print(f"[FAIL] LinuxController 创建失败: {exc}")
        result["error"] = str(exc)
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1

# post_xxx 是异步提交，必须 .wait() 才真正执行；succeeded 才是结果。
    job = ctrl.post_connection()
    job.wait()
    if not job.succeeded:
        print(f"[FAIL] connect 失败: {job.status}")
        result["error"] = f"connect {job.status}"
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1
# 连接耗时只记录、不设阈值：首次加载合成器插件会偏慢。
    result["connect_ms"] = round((time.time() - t0) * 1000, 1)
    print(f"[ ok ] connect  {result['connect_ms']} ms")

    # --- 记录项：分辨率 API 与启停能力（都不参与判定）---
    try:
# 记录项 1：分辨率 API。Linux 控制器返回 (0,0) 属于上游未补全，只记录。
# 记录项 2：start_app 不调用 —— 上游是 TODO，调了只会失败；留说明给 L5。
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
# 必须在抓帧循环之前跑：grim 也走 zwlr-screencopy，会和我们的截图抢同一个合成器，
# 并行会把 20 帧的耗时统计污染掉。顺序执行时它不影响被测指标（不在计时段内）。
# 顺带：它抓的是整块输出，所以能和我们抓的整块输出逐像素对齐（这也是只属于 L1 的对照）。
    grim_path = out_dir / "ref-grim.png"
    has_grim = grim_capture(grim_path)
# 严格模式：缺 grim 直接失败并落盘，退出码 1（环境问题），与判定失败（2）区分开。
    if not has_grim and args.require_grim:
        print("[FAIL] --require-grim 已指定，但 grim 不可用")
        result["error"] = "grim unavailable (required)"
        (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 1

    # --- 抓 n 帧 ---
    frames: list[np.ndarray] = []
    times: list[float] = []
# 每帧都计时；分布比单帧值更能说明问题（偶发慢帧会拉高 max）。
    for _ in range(args.n):
        t = time.time()
        frames.append(ctrl.post_screencap().wait().get())
        times.append((time.time() - t) * 1000.0)

# 尺寸、通道、落盘都只用第一帧：静止画面下 20 帧应完全一致，
# 用第一帧能避免把「偶发花屏帧」当成常态结论。
    first = frames[0]
    result["frame_shape"] = list(first.shape)
    result["frame_dtype"] = str(first.dtype)
    result["channel_means_bgr"] = channel_means(first)

# 四个统计量各防一件事：min 协议开销 / median 真实帧率（判定只看它）/
# p95 抖动上限 / max 离群值。p95 用「按 95% 位置取」的近似写法，样本少时退化为最大值。
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
# 静止画面下每帧的全局均值应几乎不变；标准差大说明画面在动或帧错乱。
    means = [float(f.mean()) for f in frames]
    result["frame_mean_std"] = round(float(np.std(means)), 4)
    result["frame_mean_range"] = [round(min(means), 3), round(max(means), 3)]

    # --- 干净帧落盘 ---
    frame_path = out_dir / "frame-bgr2rgb.png"
# 落一帧干净图，人工核对用（BGR -> RGB 后保存，否则红蓝互换）。
    save_png(first, frame_path)
    print(f"[info] 帧已落盘 {frame_path.name}")

    # --- 通道序交叉验证 ---
# 两个假设赛跑：翻成 RGB 比（假设 A：帧是 BGR） vs 原样比（假设 B：帧本来就是 RGB）。
# A 明显高于 B，通道序才被自证 —— 这是本层唯一的独立证据。
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
# 跳过路径：不写进 checks（那会让分母变小），也不要 False（那是环境问题冒充代码问题）。
# 打印 [skip] + 安装命令，让跳过这件事在日志里可见、可执行。
        result["grim"] = "unavailable"
        print("[skip] 未找到 grim：matches_grim / bgr_confirmed 跳过")
        print("       安装后重跑可获得通道序的独立验证：sudo apt install grim")

    # --- 判定 ---
    checks = result["checks"]
    checks["connect"] = True
# 尺寸判定只看帧本身，不再依赖 resolution API（它返回 (0,0)）。
# numpy 顺序容易记反：shape[1] 才是宽，shape[0] 是高。
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

# 只对非 None 的项求 all：跳过项既不拖累通过，也不假装通过。
# 同时把 passed / judged / skipped 全部落盘，事后能算出「当时到底验了几项」。
    judged = {k: v for k, v in checks.items() if v is not None}
    result["ok"] = all(judged.values())
    result["passed"] = sum(1 for v in judged.values() if v)
    result["judged"] = len(judged)
    (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\n=== L1 判定 ===")
    for k, v in checks.items():
# 三态输出：PASS / FAIL / SKIP，一眼能看出是「验了没过」还是「压根没验」。
        mark = "SKIP" if v is None else ("PASS" if v else "FAIL")
        print(f"  [{mark}] {k}")
    skipped = len(checks) - len(judged)
    print(f"\nL1_{'OK' if result['ok'] else 'NG'}  "
          f"passed={result['passed']}/{len(judged)}"
          + (f" (skipped={skipped})" if skipped else ""))
# 退出码约定：0 通过、1 环境/构造失败（含 --require-grim 缺 grim）、2 判定失败。
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())

# =============================================================================
# 读到这里要能回答：
#   1. 为什么判定项/记录项/跳过项要分开？（三种状态对应三种责任：代码、上游、环境）
#   2. 为什么 grim 缺失写 None 而不是 False？（环境问题不该冒充代码失败，但也不能悄悄消失）
#   3. 为什么用 grim 对照？（同协议、别人实现、同输出；自己比自己证明不了任何事）
#   4. 为什么 grim 必须在抓帧循环之前？（会和截图抢合成器，污染耗时统计）
#   5. 为什么 use_win32_vk_code 必须是 True？（pipeline 的键码是 Win32 VK）
# =============================================================================
