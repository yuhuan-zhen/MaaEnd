"""JSONC 读取：先按标准 JSON 解析，失败再去注释与尾逗号。

MaaEnd 发行版的 ``interface.json`` 与资源 bundle 里带 ``//``、``/* */`` 注释和尾逗号，标准库 ``json`` 读不了。这里的清理只覆盖注释与尾逗号，不处理单引号、无引号键这类非 JSON 语法。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_ONLY_COMMENT = re.compile(r"(?m)^\s*//.*$")
_TRAILING_COMMENT = re.compile(r'(?m)([^:"])\s*//[^"\n]*$')
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def loads_jsonc(text: str) -> Any:
    """解析一段可能带注释的 JSON 文本；标准 JSON 能过就直接返回。"""
    s = text.lstrip("\ufeff")
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 去块注释 -> 再去行首/行尾 // 注释 -> 去尾逗号
    s = _BLOCK_COMMENT.sub("", s)
    s = _LINE_ONLY_COMMENT.sub("", s)
    s = _TRAILING_COMMENT.sub(r"\1", s)
    s = _TRAILING_COMMA.sub(r"\1", s)
    return json.loads(s)


def load_jsonc(path: str | Path) -> Any:
    """读一个 JSONC 文件；BOM 按 ``utf-8-sig`` 吃掉（发行版文件带 BOM）。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    return loads_jsonc(raw.decode("utf-8-sig"))
