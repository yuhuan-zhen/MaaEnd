#!/usr/bin/env python3
"""验证资源能不能按 MXU 的那 5 个路径加载成功（Linux 控制器会额外追加 resource_linux）"""
import os
import sys

# 发行版根目录：默认 ~/maaend，可用 MAAEND_DIST / MAAEND_ROOT 覆盖（与 maaend_web.config 一致）。
ROOT = os.environ.get("MAAEND_DIST") or os.environ.get("MAAEND_ROOT") or os.path.expanduser("~/maaend")
sys.path.insert(0, f"{ROOT}/web/linux")
os.environ.setdefault("LD_LIBRARY_PATH", f"{ROOT}/maafw")

from maa.resource import Resource  # noqa: E402

PATHS = [
    f"{ROOT}/resource",
    f"{ROOT}/resource_linux",
    f"{ROOT}/web/resource_web",
    f"{ROOT}/web/linux/resource_web_linux",
    f"{ROOT}/web/resource_web_homesrv",
]

res = Resource()
for p in PATHS:
    ok_dir = os.path.isdir(p)
    job = res.post_bundle(p).wait()
    print("%-46s 目录存在=%-5s loaded=%s" % (p, ok_dir, job.succeeded))
print("整体 loaded =", res.loaded)
