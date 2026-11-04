#!/usr/bin/env python3
"""把「开始游戏（云·终末地网页版）」作为正式任务接进 interface.json 与 MXU 预设。

1) interface.json 的 import 追加 web/tasks/WebStartGame.json（任务定义放 web/ 下，
   避免升级替换 base tasks/ 时被删）
2) 网页端预设（hmuddz8 / hyasuml）把 WebStartGame 放到任务列表第 1 位并启用
"""
import json
import os
import shutil

# 发行版根目录：默认 ~/maaend，可用 MAAEND_DIST / MAAEND_ROOT 覆盖（与 maaend_web.config 一致）。
ROOT = os.environ.get("MAAEND_DIST") or os.environ.get("MAAEND_ROOT") or os.path.expanduser("~/maaend")
IFACE = f"{ROOT}/interface.json"
CFG = f"{ROOT}/config/mxu-MaaEnd.json"
IMPORT_ITEM = "web/tasks/WebStartGame.json"
WEB_ON = {"hmuddz8", "hyasuml"}
CTRL = ["Linux-Wlroots", "Linux-ScreenCast", "Linux-Gamescope"]

# --- 1) interface.json ---
shutil.copy2(IFACE, IFACE + ".bak-webstart")
d = json.load(open(IFACE, encoding="utf-8-sig"))
imp = d.setdefault("import", [])
if IMPORT_ITEM not in imp:
    imp.append(IMPORT_ITEM)
json.dump(d, open(IFACE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("import 已含 WebStartGame:", IMPORT_ITEM in imp, "| import 总数:", len(imp))

# --- 2) mxu 预设 ---
shutil.copy2(CFG, CFG + ".bak-webstart")
c = json.load(open(CFG, encoding="utf-8"))
for it in c["instances"]:
    if it["id"] not in WEB_ON:
        continue
    tasks = [t for t in (it.get("tasks") or []) if t.get("taskName") != "WebStartGame"]
    tasks.insert(0, {
        "id": "webstartgame",
        "taskName": "WebStartGame",
        "enabled": True,
        "enabledByController": dict.fromkeys(CTRL, True),
        "options": [],
    })
    it["tasks"] = tasks
    print("%-9s 任务数=%d 首位=%s" % (it["id"], len(tasks), tasks[0]["taskName"]))
json.dump(c, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
