"""路径、环境变量、端口与超时的单一真源。

部署脚本（``homesrv/*.sh``）只导出环境变量，具体默认值在这里拼装：runtime/cli 读 ``Settings``，不再各自 ``os.environ.get``。环境变量名与重构前一致，因此 cron 与部署脚本不用改。

用法::

    settings = load_settings()                  # 读 os.environ
    settings = load_settings({"MAAEND_DIST": "/opt/MaaEnd"})   # 脱环境单测
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# 单项超时（秒）：采集/送货/协议空间这类长任务给宽一点，其余任务走 DEFAULT_TIMEOUT。
TASK_TIMEOUTS: dict[str, int] = {
    "WebStartGame": 900,
    "AutoCollect": 2400,
    "DeliveryJobs": 2400,
    "SellProduct": 1800,
    "ProtocolSpace": 2400,
    "AutoStockpile": 1800,
    "AutoStockStable": 1800,
    "AutoStockStaple": 1800,
    "CreditShoppingN2": 1800,
    "VisitFriends": 1200,
    "DijiangRewards": 1200,
    "DailyRewards": 1200,
    "SeizeDeliveryJobs": 900,
    "AutoSell": 900,
    "EnvironmentMonitoring": 900,
}

DEFAULT_TIMEOUT = 1200
DEFAULT_CDP_PORT = 9334
DEFAULT_WLR_SOCKET = "/tmp/xdg-run/wayland-1"


@dataclass(frozen=True)
class Settings:
    """一次运行用到的全部路径与端口；构造后不可变，可安全传给各层。"""

    root: Path
    web: Path
    resource_dirs: tuple[Path, ...]
    log_dir: Path
    # 跑批结果的输出目录；jsonl 落在 <probe_out>/daily_linux_progress.jsonl（与重构前同一个文件）。
    probe_out: Path
    cdp_port: int
    wlr_socket: str
    agent_bin: Path
    agent_lib: Path


def _env_value(env: Mapping[str, str], name: str) -> str:
    """取环境变量的值；空串按「未设置」处理，部署脚本常把不用的变量导成空串。"""
    return (env.get(name) or "").strip()


def find_wlr_socket(env: Mapping[str, str] | None = None) -> str:
    """定位 wlroots 的 wayland socket，找不到时返回 cron 环境下最常见的兜底路径。

    cron 里通常没有 ``XDG_RUNTIME_DIR``，所以三个候选按「显式环境变量 -> 运行时目录 -> 固定路径 -> 当前 uid 的运行时目录」的顺序探测。
    """
    e = os.environ if env is None else env
    override = _env_value(e, "WLR_SOCKET")
    if override:
        return override
    uid = os.getuid() if hasattr(os, "getuid") else 0
    candidates = (
        os.path.join(e.get("XDG_RUNTIME_DIR") or "", "wayland-1"),
        DEFAULT_WLR_SOCKET,
        f"/run/user/{uid}/wayland-1",
    )
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return DEFAULT_WLR_SOCKET


def _default_root(env: Mapping[str, str]) -> Path:
    """``MAAEND_DIST`` 优先于 ``MAAEND_ROOT``，都没有时回落到 ``~/maaend``（homesrv 的部署目录）。"""
    explicit = _env_value(env, "MAAEND_DIST") or _env_value(env, "MAAEND_ROOT")
    if explicit:
        return Path(explicit)
    return Path("~/maaend").expanduser()


def _default_resource_dirs(root: Path, web: Path) -> tuple[Path, ...]:
    """列出发行版与各覆盖层资源目录，只保留真实存在的那些（缺失的由 runtime 记一行提示后跳过）。

    两套布局都要列，迁移期不能只认一边：

    * 新布局（``deploy.sh`` 把 ``assets/*`` 拍平到安装根）：``resource`` / ``resource_cloud``
      / ``resource_cloud_web``。云层与网页端薄覆盖层都挂在安装根下。
    * 旧布局（仓库内 ``web/`` 下）：``resource_web`` / ``resource_web_homesrv`` /
      ``resource_web_linux``。homesrv 现有部署仍是这一套，删掉会让它跑不起来。

    顺序即加载顺序，后加载的覆盖先加载的：发行版 → 云层 → 网页端薄覆盖 → 旧布局覆盖。
    """
    candidates = (
        root / "resource",
        root / "resource_cloud",
        root / "resource_cloud_web",
        web / "resource_web",
        web / "linux" / "resource_web_linux",
        web / "resource_web_homesrv",
    )
    return tuple(p for p in candidates if p.is_dir())


def _int_or(raw: str, default: int) -> int:
    """把环境变量解析成端口，解析不了就用默认值（写错端口不该让整批任务崩在启动前）。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """按环境变量拼出本次运行的 ``Settings``；``env`` 传 ``None`` 时读 ``os.environ``。

    传一个字典进来即可完全脱环境单测：函数不会再去读 ``os.environ``（``~`` 展开除外）。
    """
    e = os.environ if env is None else env
    root = _default_root(e)

    web_raw = _env_value(e, "MAAEND_WEB")
    web = Path(web_raw) if web_raw else root / "web"

    res_raw = _env_value(e, "MAAEND_RES_DIRS")
    # 显式给了就不做存在性过滤：缺目录由 runtime 逐条提示（与重构前一致）。
    resource_dirs = tuple(Path(p) for p in res_raw.split(":") if p) if res_raw else _default_resource_dirs(root, web)

    log_raw = _env_value(e, "MAA_LOG_DIR")
    log_dir = Path(log_raw) if log_raw else Path("~/maaend-log").expanduser()

    agent_bin_raw = _env_value(e, "MAA_AGENT_BIN")
    agent_bin = Path(agent_bin_raw) if agent_bin_raw else root / "agent" / "go-service"
    agent_lib_raw = _env_value(e, "MAA_AGENT_LIB")
    agent_lib = Path(agent_lib_raw) if agent_lib_raw else agent_bin.parent / "maafw"

    return Settings(
        root=root,
        web=web,
        resource_dirs=resource_dirs,
        log_dir=log_dir,
        probe_out=web / "probe_out",
        cdp_port=_int_or(_env_value(e, "MAAEND_WEB_CDP_PORT"), DEFAULT_CDP_PORT),
        wlr_socket=find_wlr_socket(e),
        agent_bin=agent_bin,
        agent_lib=agent_lib,
    )
