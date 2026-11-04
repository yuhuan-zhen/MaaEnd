"""兼容层：页面状态机在 :mod:`maaend_web.page`。

旧入口 ``import page_state`` 仍可用（旧文档命令与外部脚本按模块名调用）；新代码请用
``maaend_web.page``。

用法::

    from page_state import inspect, prepare    # 旧写法
    from maaend_web.page import inspect, prepare   # 新写法
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.page import State, click_css, inspect, prepare, reload_soft

__all__ = ["State", "click_css", "inspect", "prepare", "reload_soft"]
