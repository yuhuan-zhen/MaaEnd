"""兼容层：CDP 控制器在 :mod:`maaend_web.cdp`。

``wsl/attach_probe.py``、``wsl/qr_helper.py`` 仍在 ``from cdp_controller import _Sess``，
所以这里显式转出私有类。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.cdp import (
    DEFAULT_PORT,
    VK,
    CdpController,
    PageControl,
    _Sess,
    main,
    make_custom_controller,
)

__all__ = [
    "DEFAULT_PORT",
    "VK",
    "CdpController",
    "PageControl",
    "_Sess",
    "main",
    "make_custom_controller",
]

if __name__ == "__main__":
    raise SystemExit(main())
