"""从上游 VkToEvdev.h + MaaEnd pipeline 生成 fixtures/expected_keys.json。

用法（WSL）：
    python3 gen_expected_keys.py <VkToEvdev.h> <pipeline 目录> <输出 json>
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

# US 布局下这些键的 keysym。24 个键里只有字母/数字/ESC/F 键/修饰键/空格，
# 与键盘布局无关，因此可以把期望值写死；出现新键时再补。
KEYSYM_US = {
    "KEY_ESC": "Escape",
    "KEY_LEFTALT": "Alt_L",
    "KEY_LEFTSHIFT": "Shift_L",
    "KEY_LEFTCTRL": "Control_L",
    "KEY_SPACE": "space",
    "KEY_F1": "F1",
    "KEY_F2": "F2",
    "KEY_F3": "F3",
    "KEY_F4": "F4",
    "KEY_F": "f",
    "KEY_S": "s",
    "KEY_W": "w",
    "KEY_A": "a",
    "KEY_D": "d",
    "KEY_R": "r",
    "KEY_E": "e",
    "KEY_K": "k",
    "KEY_1": "1",
    "KEY_2": "2",
    "KEY_3": "3",
    "KEY_4": "4",
    "KEY_0": "0",
}


def load_vk2ev(path: str) -> dict[int, str]:
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    return {
        int(m.group(1), 16): m.group(2)
        for m in re.finditer(r"table\[(0x[0-9A-Fa-f]+)\]\s*=\s*(KEY_[A-Z0-9_]+)", text)
    }


def load_evdev(path: str = "/usr/include/linux/input-event-codes.h") -> dict[str, int]:
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    names: dict[str, int] = {}
    for m in re.finditer(r"#define\s+(KEY_[A-Z0-9_]+)\s+(0x[0-9a-fA-F]+|\d+)", text):
        value = int(m.group(2), 16) if m.group(2).startswith("0x") else int(m.group(2))
        names.setdefault(m.group(1), value)
    return names


def collect_keys(root: str) -> collections.Counter[int]:
    counter: collections.Counter[int] = collections.Counter()
    for path in pathlib.Path(root).rglob("*.json"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"key"\s*:\s*(\[[^\]]*\]|\d+)', text):
            for n in (int(x) for x in re.findall(r"-?\d+", m.group(1))):
                if 0 < n < 256:
                    counter[n] += 1
    return counter


def main() -> int:
    vk_path = sys.argv[1]
    pipeline_root = sys.argv[2]
    out_path = sys.argv[3]

    vk2ev = load_vk2ev(vk_path)
    evdev = load_evdev()
    keys = collect_keys(pipeline_root)

    num2name = {v: k for k, v in evdev.items()}
    entries: list[dict[str, object]] = []
    for vk, count in keys.most_common():
        evdev_name = vk2ev.get(vk)
        if evdev_name is None:
            entries.append(
                {
                    "vk": vk,
                    "occurrences": count,
                    "expected_evdev": None,
                    "note": "VkToEvdev.h 未覆盖，translate_key 返回 0 = KEY_RESERVED",
                }
            )
            continue
        number = evdev.get(evdev_name)
        entries.append(
            {
                "vk": vk,
                "occurrences": count,
                "expected_evdev": evdev_name,
                "evdev_code": number,
                "xkb_keycode": number + 8 if isinstance(number, int) else None,
                "expected_keysym": KEYSYM_US.get(evdev_name),
                "observed_if_not_translated": num2name.get(vk, "?"),
            }
        )

    payload: dict[str, object] = {
        "source": {
            "vk_table": "MaaFramework source/MaaLinuxControlUnit/Input/VkToEvdev.h @0fc6025c",
            "pipeline": "MaaEnd assets/resource/pipeline",
            "keymap": "US",
        },
        "totals": {"references": sum(keys.values()), "distinct": len(keys)},
        "keys": entries,
    }
    pathlib.Path(out_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"写入 {out_path}：{len(entries)} 个键值")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
