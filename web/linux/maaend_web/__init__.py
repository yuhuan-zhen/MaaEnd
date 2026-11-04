"""MaaEnd 云·终末地 Linux 运行层的纯逻辑核心。

依赖方向单向：``cli -> runtime -> core``。本包不 import ``maa``（MaaFramework），因此可以在没有框架的机器上直接单测。
"""

from __future__ import annotations
