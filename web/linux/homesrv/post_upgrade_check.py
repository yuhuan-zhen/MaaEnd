#!/usr/bin/env python3
"""升级后自检：按 run_daily 的资源层顺序加载，确认覆盖层与 base 的关键节点都在。

资源层优先读 ``MAAEND_RES_DIRS``（与 ``homesrv/lib.sh`` 的 ``mh_init`` 同一个来源），
没设时按部署布局探测，规则与 ``mh_res_dirs`` 一致：

    <root>/resource → <root>/resource_cloud → <root>/resource_cloud_web
    → <web>/linux/resource_web_linux

新目录（``resource_cloud_web``）存在时不再加载旧布局的 ``web/resource_web`` /
``web/resource_web_homesrv`` —— 否则同一批节点会加载两遍。旧布局只在新目录缺失时兜底。

退出码：0 关键节点齐全；3 有缺失（``auto_update.sh`` 据此回滚到刚备份的版本）。
"""

import os
import sys

from maa.resource import Resource

DIST = os.environ.get("MAAEND_DIST") or os.environ.get("MAAEND_ROOT") or os.path.expanduser("~/maaend")
WEB = os.environ.get("MAAEND_WEB", os.path.join(DIST, "web"))


def resource_layers():
    """返回本次要 post_bundle 的目录（只含存在的），顺序与 lib.sh 完全一致。"""
    raw = (os.environ.get("MAAEND_RES_DIRS") or "").strip()
    if raw:
        return [p for p in raw.split(":") if p]
    out = []
    base = os.path.join(DIST, "resource")
    if os.path.isdir(base):
        out.append(base)
    # 官方云层：新发行版才有；旧版的 resource_cloud_adb 故意不映射（网页端链路从没加载过它）
    for extra in ("resource_cloud", "resource_cloud_web"):
        path = os.path.join(DIST, extra)
        if os.path.isdir(path):
            out.append(path)
    if not any(p.endswith("resource_cloud_web") for p in out):
        for legacy in ("resource_web", "resource_web_homesrv"):
            path = os.path.join(WEB, legacy)
            if os.path.isdir(path):
                out.append(path)
    linux_layer = os.path.join(WEB, "linux", "resource_web_linux")
    if os.path.isdir(linux_layer):
        out.append(linux_layer)
    return out


CHECK = [
    "WebStartGameEntry",
    "WebMonthlyCard",
    "WebCloseRewards",
    "WebSessionBusy",
    "WebAlreadyInGame",
    "WebLauncherStartButton",
    "InWorld",
    "InMenuList",
    "CheckMenuListColor",
    "__ScenePrivateEndVisit",
    "__ScenePrivateWorldEnterMenuList",
    "CloseRewardsButton",
    "CloseRewardsButtonText",
    "VisitFriendsQuickVisitNext",
    "AutoStockpileEnaureElasticClicked",
]


def main():
    """加载所有资源层，逐个查关键节点；缺一个就 rc=3。"""
    dirs = resource_layers()
    if not dirs:
        print("[X] 一个资源层都没找到（MAAEND_DIST=%s）" % DIST)
        return 3
    res = Resource()
    for path in dirs:
        ok = res.post_bundle(path).wait()
        print("load %-28s -> %s" % (os.path.basename(path), ok))

    missing = []
    for name in CHECK:
        ok = bool(res.get_node_data(name))
        if not ok:
            missing.append(name)
        print("  %-40s %s" % (name, "OK" if ok else "缺失"))

    print("\n结果: %d/%d 存在" % (len(CHECK) - len(missing), len(CHECK)))
    return 0 if not missing else 3


if __name__ == "__main__":
    sys.exit(main())
