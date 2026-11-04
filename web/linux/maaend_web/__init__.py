"""MaaEnd 云·终末地 Linux 运行层。

分三层，依赖方向单向：``cli -> runtime -> core``。

- **core**（纯逻辑，不 import ``maa``）：``config`` / ``jsonc`` / ``preset`` / ``plan`` /
  ``results`` / ``page`` / ``page_js`` / ``page_control``
- **runtime**（碰 ``maa``，但导入都写在函数体内）：``framework`` / ``recovery`` / ``overlay``
- **cli**（只做 argparse 与编排）：``cli.daily`` / ``cli.overlay``

没有安装 MaaFramework 的机器可以 ``import maaend_web.config`` 并跑全部 core 单测。

用法::

    from maaend_web.config import load_settings
    from maaend_web.preset import load_preset
"""
