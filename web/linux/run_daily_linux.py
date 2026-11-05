"""兼容入口：真正的实现搬到了 ``maaend_web/cli/daily.py``。

生产 cron 与 ``homesrv/*.sh`` 都直接调这个路径，所以文件名与命令行参数都不变；
这里只把本目录放进 ``sys.path`` 再转交给 CLI。argparse 阶段不 import ``maa``，
没有框架的机器也能 ``--help`` / ``--dry-run``。

除了 ``main``，这里还保留旧模块级的常量与函数名：``homesrv/map_probe.py``
仍在 ``from run_daily_linux import DIRS, SOCK, log, start_agent``，
``devtools/calibrate_turn.py`` 仍在 ``R.make_controller(SOCK)`` / ``R.start_agents(res, ...)``。
这些名字是兼容契约，不要删。

用法::

    python3 run_daily_linux.py --instance <预设 id> --dry-run
    python3 run_daily_linux.py --tasks WebStartGame --attempts 1

退出码：见 :mod:`maaend_web.cli.daily`（0 全成功 / 3 资源 / 4 控制器 / 7 有任务失败）。
"""

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.cli.daily import log, main
from maaend_web.config import TASK_TIMEOUTS, load_settings
from maaend_web.framework import ensure_preload, ensure_relative_move_support, find_wlr_socket
from maaend_web.framework import make_controller as _make_controller
from maaend_web.framework import start_agent as _start_agent
from maaend_web.framework import start_agents as _start_agents

_settings = load_settings()

# 旧模块级常量的等价物（旧代码按模块属性读，不要改成函数）。
DIST = str(_settings.root)
WEB = str(_settings.web)
DIRS = [str(p) for p in _settings.resource_dirs]
SOCK = _settings.wlr_socket
AGENT_BIN = str(_settings.agent_bin)
AGENT_DIR = str(_settings.agent_bin.parent)
AGENT_LIB = str(_settings.agent_lib)
OUT_JSONL = str(_settings.probe_out / "daily_linux_progress.jsonl")
TIMEOUTS = TASK_TIMEOUTS

__all__ = [
    "AGENT_BIN",
    "AGENT_DIR",
    "AGENT_LIB",
    "DIRS",
    "DIST",
    "OUT_JSONL",
    "SOCK",
    "TIMEOUTS",
    "WEB",
    "ensure_preload",
    "ensure_relative_move_support",
    "find_wlr_socket",
    "log",
    "main",
    "make_controller",
    "record",
    "start_agent",
    "start_agents",
]


def make_controller(sock: str | None = None):
    """旧签名 ``make_controller(sock)``：按 wlroots 控制器创建。

    新实现是 ``make_controller(kind, settings)``，这里只做参数适配，
    并允许调用方覆盖 socket（``calibrate_turn.py`` 会传自己的 SOCK）。
    """
    settings = replace(_settings, wlr_socket=sock or SOCK)
    return _make_controller("wlroots", settings, log=log)


def start_agent(
    res: Any,
    controller_name: str = "Linux-Wlroots",
    resource_name: str = "官服-网页端",
    bin_path: str | None = None,
    tag: str | None = None,
):
    """旧签名 ``start_agent(res, controller_name, resource_name)``。"""
    return _start_agent(
        res,
        _settings,
        bin_path=Path(bin_path) if bin_path else None,
        tag=tag,
        controller_name=controller_name,
        resource_name=resource_name,
        log=log,
    )


def start_agents(
    res: Any,
    controller_name: str = "Linux-Wlroots",
    resource_name: str = "官服-网页端",
    bins: list[str] | None = None,
):
    """旧签名 ``start_agents(res, controller_name, resource_name, bins=None)``。"""
    if bins is None:
        return _start_agents(
            res,
            _settings,
            controller_name=controller_name,
            resource_name=resource_name,
            log=log,
        )
    return [start_agent(res, controller_name, resource_name, bin_path=b) for b in bins]


def record(obj: dict[str, Any]) -> None:
    """旧行为：把一条任务结果追加到 ``OUT_JSONL``（保留给旧调用点）。"""
    os.makedirs(os.path.dirname(OUT_JSONL), exist_ok=True)
    with open(OUT_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
