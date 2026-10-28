#!/usr/bin/env python3
"""把 web/resource_web 的覆盖层拆成三层，用来做「兼容性阶梯」验证。

目的：回答「别人写的节点能不能直接拿来用」。拆完以后可以按层加载：

    MAAEND_RES_DIRS=<安装目录>/resource                 # ① 纯上游
    MAAEND_RES_DIRS=<安装目录>/resource:.../resource_web_min        # ② + 数值覆盖
    ...:.../resource_web_structural                                 # ③ + 结构覆盖
    ...:.../resource_web_startup                                    # ④ + 启动链（= 现状）

层级定义：
  resource_web_min         颜色阈值 / ROI / 时序 —— 上游改同节点只会盖数值，不和结构打架
  resource_web_structural  next 链、识别类型 —— **兼容性杀手**，目标是最终清零
  resource_web_startup     网页启动链 + 挡屏 —— launcher 接管后整层删除

用法：python3 split_overlay.py [--write]
不带 --write 只报告分组结果。
"""

from __future__ import annotations

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "resource_web"))

# 启动链：把页面从「落地页/排队/月卡」推到游戏内 —— launcher --prepare 接管
STARTUP = {
    "WebStartGameEntry", "WebAlreadyInGame", "WebLauncherStartButton", "WebQueueDetected",
    "WebWaitInGame", "WebTitleContinue", "WebSessionBusy", "WebMonthlyCard",
    "WebTitleClickToContinue",
}

# 挡屏：网页特有的遮罩/弹窗 —— 抹平注入 + launcher 处理
BLOCKER = {
    "WebCloseRewards", "WebAnyExitEsc",
    "__ScenePrivateCloudClickToContinue", "WebCloseProtocolPass",
}

# 结构覆盖：改 next 链或识别类型，上游一改就冲突
STRUCTURAL = {
    "__ScenePrivateAnyExit",              # recognition → DirectHit（ESC 一步退出）
    "__ScenePrivateWorldEnterMenuList",   # next 去掉 __SceneImageCheck
    "SceneAnyEnterWorld",                 # next 插入关闭通行证全屏页
}

LAYERS = {
    "resource_web_min": "数值覆盖（颜色 / ROI / 时序）",
    "resource_web_structural": "结构覆盖（next / 识别类型）",
    "resource_web_startup": "启动链 + 网页挡屏",
}


def main(write: bool) -> int:
    nodes = json.load(open(os.path.join(SRC, "pipeline", "nodes.json"), encoding="utf-8-sig"))
    groups: dict[str, dict] = {k: {} for k in LAYERS}
    unknown = []

    for name, node in nodes.items():
        if name in STARTUP or name in BLOCKER:
            groups["resource_web_startup"][name] = node
        elif name in STRUCTURAL:
            groups["resource_web_structural"][name] = node
        elif name in nodes and name.startswith("Web"):
            unknown.append(name)   # 新的 Web* 节点没归类，提示一下
            groups["resource_web_startup"][name] = node
        else:
            groups["resource_web_min"][name] = node

    total = 0
    for layer, desc in LAYERS.items():
        names = sorted(groups[layer])
        print("%-26s %2d 个节点  %s" % (layer, len(names), desc))
        for n in names:
            print("    -", n)
        total += len(names)
    print("合计 %d / 原 %d" % (total, len(nodes)))
    if unknown:
        print("! 未归类、按启动链处理：", unknown)

    if not write:
        print("\n（只报告；加 --write 才写盘）")
        return 0

    for layer in LAYERS:
        root = os.path.join(HERE, layer)
        pipe = os.path.join(root, "pipeline")
        os.makedirs(pipe, exist_ok=True)
        with open(os.path.join(pipe, "nodes.json"), "w", encoding="utf-8") as f:
            json.dump(groups[layer], f, ensure_ascii=False, indent=4)
            f.write("\n")
        print("写出", os.path.join(pipe, "nodes.json"))

    # 模板（PhotoIcon 等）是给上游节点用的，跟着数值层走
    src_img = os.path.join(SRC, "image")
    if os.path.isdir(src_img):
        dst_img = os.path.join(HERE, "resource_web_min", "image")
        shutil.rmtree(dst_img, ignore_errors=True)
        shutil.copytree(src_img, dst_img)
        print("复制模板 →", dst_img)

    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
