"""兼容层：浮层控制在 :mod:`maaend_web.overlay`。

``homesrv/chrome_homesrv.sh`` 与 ``homesrv/lib.sh`` 仍直接跑
``python3 overlay_ctl.py --check|--once|--watch``，路径与参数不变。

用法::

    python3 overlay_ctl.py --check      # 只探测
    python3 overlay_ctl.py --once       # 注入一次
    python3 overlay_ctl.py --watch      # 常驻巡检

退出码：0 = 全隐藏 / 注入成功 / 正常退出；1 = 仍有可见浮层或注入失败；2 = 连不上 CDP。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.overlay import (
    DEVTOOLS_DEFAULT,
    INJECT_METHOD,
    URL_HINT_DEFAULT,
    Sess,
    all_hidden,
    inject,
    inject_commands,
    list_pages,
    main,
    needs_reinject,
    overlay_fingerprint,
    policy_commands,
    policy_path,
    policy_source,
    run_check,
    run_once,
    run_watch,
    select_targets,
    summarize,
)

__all__ = [
    "DEVTOOLS_DEFAULT",
    "INJECT_METHOD",
    "URL_HINT_DEFAULT",
    "Sess",
    "all_hidden",
    "inject",
    "inject_commands",
    "list_pages",
    "main",
    "needs_reinject",
    "overlay_fingerprint",
    "policy_commands",
    "policy_path",
    "policy_source",
    "run_check",
    "run_once",
    "run_watch",
    "select_targets",
    "summarize",
]

if __name__ == "__main__":
    raise SystemExit(main())
