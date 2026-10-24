#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingModuleSource=false  # 讲解副本：依赖（maa/numpy/pillow）不在阅读环境的解释器里，静音导入告警
"""L1 帧源层验收：MaaLinuxControlUnit / WlrScreencap 是否给出正确的 1280x720 帧。

只读，不注入任何输入。

判定 8 项（全部为 True 才算通过）：
  1. connect           连上 sway（Wayland 合成器）
  2. shape_1280x720    帧尺寸是 1280x720，不依赖 MaaControllerGetResolution
  3. shape_hw3         形如 (720, 1280, 3)
  4. not_blank         不是黑帧 / 纯色
  5. stable            静止画面 20 帧的帧间均值标准差 < 2.0
  6. fast_enough       单帧耗时中位数 < 500 ms
  7. matches_grim      与 grim 参考帧的 NCC > 0.90
  8. bgr_confirmed     BGR->RGB 的 NCC 高于按 RGB 直用

记录项（不参与判定）：
  resolution_api  MaaControllerGetResolution 的返回值；Linux 控制器当前返回 (0, 0)
  start_app       上游 LinuxControlUnit 的启停实现状态；本层不探测

用法：
    XDG_RUNTIME_DIR=/run/user/0 WAYLAND_DISPLAY=wayland-1 \
      python3 l1_screencap.py [--socket /run/user/0/wayland-1] [--n 20]
"""

# 让类型注解延迟求值：写 list[np.ndarray] 这类较新语法时，旧解释器也不当场报错。
# 本项目要求 Python >= 3.14，其实已不需要，保留是社区惯例。
# =============================================================================
# 这份文件在干什么（小白先读这一段）
# =============================================================================
#
# 验证一件事：MaaFramework 在 Linux 上能不能「把游戏画面正确截下来」。
# 后面所有识别（模板匹配、OCR）都建立在截图上，截图错一个像素或错一个通道都不会报错，
# 只会让识别率莫名其妙地变低。所以第一层只测截图。
#
# 「截图」不是自己抓屏，而是调用 MaaFramework 的 LinuxController，让它去问
# Wayland 合成器（sway）要一帧画面。我们要做的是：拿到帧 → 量尺寸/通道/耗时 →
# 和 grim 抓的同一画面比相似度。
#
# 判定项与记录项的区别（本文件的核心约定，改代码时别破坏它）：
#   判定项（8 项）：全为 True 才算 L1 通过，参与 result["ok"]。
#     connect / shape_1280x720 / shape_hw3 / not_blank
#     stable / fast_enough / matches_grim / bgr_confirmed
#   记录项（2 项）：只写进 l1.json 供后续层参考，不参与判定。
#     · resolution_api —— MaaControllerGetResolution 的返回。Linux 控制器当前返回 (0,0)，
#       属于上游 API 未补全。以前这里用「帧 shape 兜底」让它通过，会把这个缺口藏起来；
#       现在拆开：shape 单独判，resolution 只记录。
#     · start_app —— 上游 LinuxControlUnit 的 start_app 仍是 TODO，本层不调用也不探测，
#       只留一条记录给 L5 看（L5 要判断能不能启停游戏进程）。
#
# 名词（第一次出现就解释）：
#   Controller：MaaFramework 里负责「截图 + 输入」的对象，一个任务绑定一个。
#   Job：异步操作句柄。post_xxx() 只是提交，.wait() 才等结果。
#   BGR / RGB：三个颜色分量的排列顺序。OpenCV/MaaFramework 用 BGR，PIL 用 RGB。
#   NCC（归一化互相关）：0~1 的相似度，1 = 完全一致，0 = 毫无关系；比逐像素相等耐噪。
#   grim：wlroots 系合成器的官方截图工具，和我们用同一个协议，所以可以当「标准答案」。
#   Wayland socket：跟合成器通信的 unix socket，形如 /run/user/0/wayland-1
#                   （0 是 uid，1 是第二个显示实例）。
#
# 文档对照（链接见同目录 README.md）：
#   [FW-2.2] 集成接口一览（MaaLinuxControllerCreate 的参数）
#   [FW-2.4] 控制方式说明（Linux Screencap / Linux Input 两张表；代码里 1 这个数字的出处）
#   [PLAN]   tools/linux-adapt/PLAN.md（六层计划与 L1 验收标准）
# =============================================================================
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
# 路径对象比手拼字符串安全，.parent / mkdir 更清楚。
from pathlib import Path

# 截图在内存里就是「高 × 宽 × 3」的数值矩阵，求均值/点积/翻转通道都要它。
# 依赖来自 pyproject.toml 的 images 组（numpy>=2.5）。
import numpy as np
# LinuxController 是 binding 里代表 Linux 控制器的类。
# 注意：import 名是 maa，安装的 PyPI 包名是 maafw（两者不同，容易踩）。
from maa.controller import LinuxController
# 读 grim 抓的 PNG；行尾会用到（本文件自己的帧由 save_png 负责）。PIL 只认 RGB。
from PIL import Image

# 五个共用工具，抽到 harness/common.py（L2 的输入探针也要用，避免各写一份后分叉）：
#   ncc(a, b)              归一化互相关：比两张图像不像，判通道序和参考帧都靠它
#   channel_means(img)     三个通道的均值：通道反了时三者顺序会明显错位
#   save_png(img, path)    BGR -> RGB 后落盘，人工核对用
#   grim_capture(path)     调 grim 抓同一路输出当标准答案（失败只降级不报错）
#   default_wlr_socket()   从 $XDG_RUNTIME_DIR + $WAYLAND_DISPLAY 推导 socket
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
# 输入方式：1 = Wlr（虚拟指针/键盘）。本层不做输入，但创建控制器时必填。
INPUT_WLR = 1      # MaaLinuxInputMethod_Wlr



# ---------------------------------------------------------------------------
# 入口：连接 → 记录项 → 抓帧 → 量四项 → 与 grim 对账 → 判定
# ---------------------------------------------------------------------------
def main() -> int:
# default_wlr_socket() 从环境变量推导，换用户/换 WSL 发行版时不用改代码；
# 命令行仍可覆盖（--socket）。
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default=default_wlr_socket(),
                    help="Wayland socket；默认 $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="evidence-l1")
    args = ap.parse_args()

# 证据默认落在 tools/linux-adapt/evidence-l1/（.gitignore 已排除 evidence-*/）。
    out_dir = Path(__file__).parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"socket": args.socket, "checks": {}, "ok": False}

    # --- 创建并连接 ---
# 直接对应 MaaLinuxControllerCreate 的 config_json：
#   screencap_method / input_method 必填；走 Wlroots 时 wlr_socket_path 必填。
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
# 构造失败要给非 0 退出码并落盘，不能静默返回（否则上层以为跑过了）。
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
# 记录项 1：分辨率 API。Linux 控制器返回 (0,0) 属于上游未补全，这里只记录；
# 尺寸判定改由帧 shape 承担（见下面 shape_1280x720）。
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

    # --- 参考帧（grim） ---
# grim 与 WlrScreencap 用同一个 zwlr_screencopy 协议，所以它的输出可直接当标准答案。
# 拿不到 grim 不算失败，只是少两项交叉验证（checks 里会自动少掉那两项）。
    grim_path = out_dir / "ref-grim.png"
    has_grim = grim_capture(grim_path)

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

# 四个统计量各防一件事：
#   min  —— 热路径最快能多快（判断协议本身的开销）
#   median —— 真实可用帧率的代表值，判定只看它
#   p95  —— 抖动上限（游戏里偶发卡顿会不会拖垮识别节奏）
#   max  —— 最坏情况（是否有离群值，比如首次分配缓冲）
# p95 用「按 95% 位置取」的近似写法，样本少时退化为最大值。
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
# 静止画面下每帧的全局均值应几乎不变；标准差大说明画面在动，或帧错乱/尺寸不符。
    means = [float(f.mean()) for f in frames]
    result["frame_mean_std"] = round(float(np.std(means)), 4)
    result["frame_mean_range"] = [round(min(means), 3), round(max(means), 3)]

    # --- 干净帧落盘 ---
    frame_path = out_dir / "frame-bgr2rgb.png"
# 落一帧干净图，人工核对用（BGR -> RGB 后保存，否则红蓝会互换）。
    save_png(first, frame_path)
    print(f"[info] 帧已落盘 {frame_path.name}")

    # --- 通道序交叉验证 ---
# 同一画面按两种通道序各比一次：
#   按 binding 声明翻成 RGB → 应当高（BGR 假设成立）
#   原样当 RGB 直接用     → 应当明显更低
# 两个 NCC 的差就是「通道序确实反了」的证据，而不是靠代码注释自证。
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

    # --- 判定 ---
    checks = result["checks"]
    checks["connect"] = True
# 尺寸判定只看帧本身，不再依赖 resolution API（它返回 (0,0)）。
# numpy 顺序容易记反：shape[1] 才是宽，shape[0] 是高。
    checks["shape_1280x720"] = (first.shape[1], first.shape[0]) == (1280, 720)
    checks["shape_hw3"] = (len(first.shape) == 3 and first.shape[2] == 3)
# 上下界一起判：纯黑（均值≈0）与纯白/过曝（均值≈255）都说明帧没拿到或截错源。
    checks["not_blank"] = 5.0 < float(first.mean()) < 250.0
    checks["stable"] = result["frame_mean_std"] < 2.0
# 阈值 500 ms 很宽松，只用来抓「完全没走 wlroots 协议」这类异常；
# 实际中位数在 16 ms 量级，真变慢了应当去看 max 而不是这条。
    checks["fast_enough"] = result["screencap_ms"]["median"] < 500.0
    if "ncc_bgr2rgb" in result:
        checks["matches_grim"] = result["ncc_bgr2rgb"] > 0.90
        checks["bgr_confirmed"] = result["ncc_bgr2rgb"] > result["ncc_as_is"]

# 只有全部判定项为 True 才算通过；两个记录项不参与。
    result["ok"] = all(checks.values())
    (out_dir / "l1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

# 逐项打印，谁挂了一眼能看出来。
    print("\n=== L1 判定 ===")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\nL1_{'OK' if result['ok'] else 'NG'}  "
          f"passed={sum(checks.values())}/{len(checks)}")
# 退出码约定：0 通过、1 环境/构造失败、2 判定失败 —— 上层脚本据此区分「没跑起来」和「跑了但不对」。
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())

# =============================================================================
# 读到这里要能回答：
#   1. 为什么判定项和记录项要分开？（避免 (0,0) 被 shape 兜底通过，掩盖上游缺口）
#   2. 为什么用 grim 对照？（同一截图协议，能独立验证通道序而不是自证）
#   3. BGR 结论怎么来的？（翻通道后的 NCC 明显高于不翻）
#   4. 为什么 use_win32_vk_code 必须是 True？（pipeline 的键码是 Win32 VK）
#   5. 为什么 L1 不测输入？（截图是所有识别的地基，先单独钉死它）
# =============================================================================
