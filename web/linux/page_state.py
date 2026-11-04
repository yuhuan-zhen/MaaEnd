"""兼容层：页面状态机在 :mod:`maaend_web.page`。

旧入口 ``import page_state`` 仍可用；新代码请用 ``maaend_web.page``。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.page import State, click_css, inspect, prepare, reload_soft

__all__ = ["State", "click_css", "inspect", "prepare", "reload_soft"]
