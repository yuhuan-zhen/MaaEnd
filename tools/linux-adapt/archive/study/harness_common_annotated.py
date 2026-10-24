#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingModuleSource=false  # 讲解副本：依赖（maa/numpy/pillow）不在阅读环境的解释器里，静音导入告警
"""L1 / L2 共用的验收工具。

抽出来的理由：L1（帧源）与 L2（输入原语）都要「比两张图像不像」「把帧落盘」
「看通道均值」「抓一张 grim 参考帧」。放在这里一次，避免两边各写一份后分叉。

不依赖 MaaFramework，只依赖 numpy / pillow。
"""

# 延迟求值类型注解（list[float] 这类写法）。
# =============================================================================
# harness/common.py 的精读版
# =============================================================================
#
# 为什么有这个文件：L1（帧源）与 L2（输入原语）都要「比两张图像不像」「把帧落盘」
# 「看通道均值」「抓一张 grim 参考帧」。各写一份早晚分叉；抽到一处后两份验收脚本
# 共用同一套判定口径。
#
# 刻意不依赖 MaaFramework：只依赖 numpy / pillow。这样它也能在没装 maafw 的环境里跑，
# 便于单独验证「图像比较」这段逻辑本身对不对。
#
# 五个函数的分工：
#   default_wlr_socket()  环境变量 -> socket 路径（替代写死的 /run/user/0/wayland-1）
#   ncc()                 相似度（判通道序、判与参考帧一致）
#   channel_means()       通道均值（通道反了时三者顺序明显错位，作为粗诊断）
#   grim_capture()        抓参考帧（失败只降级，不抛异常——参考帧不是必需品）
#   save_png()            BGR -> RGB 落盘（PIL 只认 RGB）
# =============================================================================
from __future__ import annotations

# 读 $XDG_RUNTIME_DIR / $WAYLAND_DISPLAY。
import os

# 调 grim 这个外部命令。
import subprocess

# 路径对象；grim 需要 str 参数，所以调用处会 str()。
from pathlib import Path

# 矩阵运算：均值、点积、翻转通道。
import numpy as np

# 只用于落盘（Image.fromarray）。
from PIL import Image


# ---------------------------------------------------------------------------
# 原来 --socket 默认值写死 /run/user/0/wayland-1：换用户（uid 不是 0）或换显示实例
# （wayland-0 / wayland-1）就错，而且 L2/L5 会把同一个硬编码再抄一遍。
# ---------------------------------------------------------------------------
def default_wlr_socket() -> str:
    """推导 Wayland socket 路径：$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY。

    两个环境变量任一缺失时回退到 root + wayland-0，与上游文档的示例一致。
    WAYLAND_DISPLAY 是绝对路径时直接用它（Wayland 允许这么写）。
    """
    # WAYLAND_DISPLAY 允许是绝对路径，那种情况直接返回，不再拼 runtime 目录。
    display = os.environ.get("WAYLAND_DISPLAY") or "wayland-0"
    if display.startswith("/"):
        return display
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        # Windows 没有 os.getuid（这里只是为了让「导入/静态检查」不崩，
        # 真正的验收脚本只在 Linux 上跑）。
        uid = os.getuid() if hasattr(os, "getuid") else 0
        runtime = f"/run/user/{uid}"
    return os.path.join(runtime, display)


# ---------------------------------------------------------------------------
# 归一化互相关：先各自减去均值（去掉整体亮度差），再算余弦相似度。
# 为什么不用逐像素相等：截图链路可能有轻微噪声/压缩差异，逐像素会误判。
# ---------------------------------------------------------------------------
def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关（灰度、零均值）：1 表示完全一致，0 表示毫无关系。"""
    # 转 float64 再算，避免 uint8 相减溢出（0-255 会绕回 255）。
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float("nan") if denom == 0 else float(a.dot(b) / denom)


# 通道均值只是粗诊断：通道序反了时三个数会整体错位，肉眼能看出不对。
def channel_means(img: np.ndarray) -> list[float]:
    """三个通道各自的均值，用来快速看通道序是不是反了。"""
    return [round(float(img[:, :, i].mean()), 3) for i in range(img.shape[2])]


# ---------------------------------------------------------------------------
# 参考帧不是必需品：拿不到就返回 False，让调用方少做两项交叉验证，
# 而不是让整层验收失败（环境里没装 grim 是常见情况）。
# 用 check=True + 捕获异常，是为了把「grim 不存在 / 合成器不认」统一成 False。
# ---------------------------------------------------------------------------
def grim_capture(out_path: Path) -> bool:
    """用 grim 抓同一路 wlroots 输出作为参考（同 zwlr_screencopy 协议）。"""
    try:
        subprocess.run(
            ["grim", str(out_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return out_path.exists()
    except Exception:
        return False


# bgr 默认 True：MaaFramework 给的是 BGR，PIL 只认 RGB，落盘前必须翻。
# 翻法用切片 [:, :, ::-1]，不复制整块内存之外的额外开销。
def save_png(img: np.ndarray, out_path: Path, bgr: bool = True) -> None:
    """BGR -> RGB 后落盘（PIL 只认 RGB）。"""
    arr = img[:, :, ::-1] if bgr and img.shape[2] == 3 else img
    Image.fromarray(arr.astype(np.uint8)).save(out_path)
