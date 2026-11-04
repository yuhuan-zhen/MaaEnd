"""兼容层：浮层控制在 :mod:`maaend_web.overlay`。

``homesrv/chrome_homesrv.sh`` 与 ``homesrv/lib.sh`` 仍直接跑
``python3 overlay_ctl.py --check|--once|--watch``，路径与参数不变。
"""

from __future__ import annotations

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
