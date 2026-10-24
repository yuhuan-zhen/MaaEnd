#!/usr/bin/env python3
"""L1 / L2 共用的验收工具。

抽出来的理由：L1（帧源）与 L2（输入原语）都要「比两张图像不像」「把帧落盘」
「看通道均值」「抓一张 grim 参考帧」。放在这里一次，避免两边各写一份后分叉。

不依赖 MaaFramework，只依赖 numpy / pillow。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


def default_wlr_socket() -> str:
    """推导 Wayland socket 路径：$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY。

    两个环境变量任一缺失时回退到 root + wayland-0，与上游文档的示例一致。
    WAYLAND_DISPLAY 是绝对路径时直接用它（Wayland 允许这么写）。
    """
    display = os.environ.get("WAYLAND_DISPLAY") or "wayland-0"
    if display.startswith("/"):
        return display
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, display)


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关（灰度、零均值）：1 表示完全一致，0 表示毫无关系。"""
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float("nan") if denom == 0 else float(a.dot(b) / denom)


def channel_means(img: np.ndarray) -> list[float]:
    """三个通道各自的均值，用来快速看通道序是不是反了。"""
    return [round(float(img[:, :, i].mean()), 3) for i in range(img.shape[2])]


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


def save_png(img: np.ndarray, out_path: Path, bgr: bool = True) -> None:
    """BGR -> RGB 后落盘（PIL 只认 RGB）。"""
    arr = img[:, :, ::-1] if bgr and img.shape[2] == 3 else img
    Image.fromarray(arr.astype(np.uint8)).save(out_path)
