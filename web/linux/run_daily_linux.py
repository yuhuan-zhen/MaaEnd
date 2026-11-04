"""兼容入口：真正的实现搬到了 `maaend_web/cli/daily.py`。

生产 cron 与 `homesrv/*.sh` 都直接调这个路径，所以文件名与命令行参数都不变；
这里只把本目录放进 `sys.path` 再转交给 CLI。argparse 阶段不 import `maa`，
没有框架的机器也能 `--help` / `--dry-run`。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.cli.daily import main

if __name__ == "__main__":
    sys.exit(main())
