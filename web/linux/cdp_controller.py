"""兼容层：CDP 相关实现在 ``maaend_web.page_control`` 与 ``devtools/cdp.py``。

拆分原因：CDP **控制器**（取 ``<video>`` 原生帧 + 注入输入）不是生产路径，生产走框架的
C++ ``Linux-Wlroots``，所以它搬进了 ``devtools/``；而**页面控制层**（状态机 / 策略注入 /
页面内点击）在生产也要用，留在 ``maaend_web/``。

仍有外部调用点按旧模块名取值（``web/tools/cdp_probe.py``、``devtools/wsl/*.py``），
所以这里显式转出两个来源的全部公开名字，包括私有会话类 ``_Sess``。

用法::

    from cdp_controller import make_custom_controller   # 旧写法，仍可用
    from devtools.cdp import make_custom_controller     # 新写法（仅调试）
    from maaend_web.page_control import PageControl     # 新写法（生产也用这个）

退出码：``python3 cdp_controller.py`` 转发 ``devtools/cdp.py`` 的自测 CLI，恒为 0
（抓帧是否成功看打印）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from devtools.cdp import VK, CdpController, make_custom_controller
from devtools.cdp import main as _cdp_main
from maaend_web.page_control import DEFAULT_PORT, PageControl, install_policy, target_url
from maaend_web.page_control import Sess as _Sess

__all__ = [
    "DEFAULT_PORT",
    "VK",
    "CdpController",
    "PageControl",
    "_Sess",
    "install_policy",
    "main",
    "make_custom_controller",
    "target_url",
]


def main(argv: list[str] | None = None) -> int:
    """转发 ``devtools/cdp.py`` 的自测 CLI（``--selftest`` / ``--click`` / ``--key``）。"""
    return _cdp_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
