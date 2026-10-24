#!/usr/bin/env python3
"""统计 MaaEnd pipeline 里的按键数字，按 VK 与 evdev 两种解释并排对照。

用法（在 WSL 里跑，需要 linux/input-event-codes.h）：

    python3 keycensus.py [VkToEvdev.h 路径] [pipeline 目录]

默认值指向本机常见位置，换机器时用参数覆盖。
"""

from __future__ import annotations

import collections
import pathlib
import re
import sys

DEFAULT_VK = "/tmp/VkToEvdev.h"
DEFAULT_PIPELINE = "/mnt/d/桌面/常用/面向MMAEND项目/MaaEnd-linux-adapt/assets/resource/pipeline"


def load_vk_table(path: str) -> dict[int, str]:
    """从上游 VkToEvdev.h 抽 `table[0xNN] = KEY_XXX` 的映射。"""
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    return {
        int(m.group(1), 16): m.group(2)
        for m in re.finditer(r"table\[(0x[0-9A-Fa-f]+)\]\s*=\s*(KEY_[A-Z0-9_]+)", text)
    }


def load_evdev_names() -> dict[int, str]:
    """从内核头文件抽 evdev 数值 → KEY_* 名字，用于「直读」对照。"""
    text = pathlib.Path("/usr/include/linux/input-event-codes.h").read_text(
        encoding="utf-8", errors="ignore"
    )
    names: dict[int, str] = {}
    for m in re.finditer(r"#define\s+(KEY_[A-Z0-9_]+)\s+(0x[0-9a-fA-F]+|\d+)", text):
        value = int(m.group(2), 16) if m.group(2).startswith("0x") else int(m.group(2))
        names.setdefault(value, m.group(1))
    return names


def collect_keys(root: str) -> collections.Counter[int]:
    """收集所有 `"key": <n>` / `"key": [n, m]` 里的数字。"""
    counter: collections.Counter[int] = collections.Counter()
    for path in pathlib.Path(root).rglob("*.json"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"key"\s*:\s*(\[[^\]]*\]|\d+)', text):
            for n in (int(x) for x in re.findall(r"-?\d+", m.group(1))):
                if 0 < n < 256:
                    counter[n] += 1
    return counter


def main() -> int:
    vk_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VK
    pipeline_root = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PIPELINE

    vk_table = load_vk_table(vk_path)
    evdev_names = load_evdev_names()
    keys = collect_keys(pipeline_root)

    if not keys:
        print(f"没找到任何 key，检查目录：{pipeline_root}")
        return 1

    total = sum(keys.values())
    print(f"总按键引用次数: {total}  不同键值: {len(keys)}")
    print()
    print("| 键值 | 次数 | 按 VK 读（开了转换） | 按 evdev 直读（默认 false） |")
    print("| --- | --- | --- | --- |")
    for value, count in keys.most_common():
        print(
            f"| {value} | {count} | {vk_table.get(value, '（表内无映射→0）')} "
            f"| {evdev_names.get(value, '?')} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
