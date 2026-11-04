#!/usr/bin/env python3
"""AutoEssence 基质链只读诊断：日志时间线 + 云层/官方 resource_cloud 节点差集 + 可选只读识别评分。

背景
----
云·终末地（Linux 网页端）报 AutoEssence 0/8。判 0/8 的链条有三层，本脚本把「证据在哪一层」钉死：

1. **静态可证**：`assets/resource_cloud_adb` 与官方 `assets/resource_cloud` 的差集。官方新增的
   `AutoEssence/CommonNodes/Capacity.json`（2 节点）我们云层完全没有：`AutoEssenceCapacityClickSave`
   只做 next 覆盖，另加 `AutoEssenceCapacitySaveClosed` 先确认筛选弹窗已关再读「已选择 N/200」。
   官方注释逐字写明云端延迟下「点保存后头几帧仍是筛选弹窗，底栏静止就放行，会读到已选择 0/200」。
   这是代码级确定的缺陷，与本轮哪份日志无关。
2. **日志可证**：日志里跑到哪一步死的、死因是哪行。注意日志可能来自**旧部署**——本脚本会比较日志
   末条时间与代码 mtime，早于代码部署的观测一律标成 stale，不当作当前代码的失败证据。
3. **需实机复验**：部署重构版后重跑一次，看失败节点是否变化；`--probe` 用一次只读截图对容量判定
   的 OCR 节点打分，验证「这一帧到底读到几个」。

只读边界
--------
不点击、不按键、不派发 pipeline 任务。`--probe` 只做 `post_screencap` + `post_recognition`，
沿用 homesrv `map_probe.py` 的既有做法。默认不 probe。

用法
----
    # 1) 纯离线：日志 + 静态差集（无游戏、无 maa 也能跑）
    python3 web/linux/homesrv/diagnose_essence.py \\
        --log ~/maaend/essence.log --root ~/maaend --repo ~/maaend --official ~/maaend-official

    # 2) 追加只读识别评分（游戏在前台时；只截图不输入）
    python3 web/linux/homesrv/diagnose_essence.py --log ~/maaend/essence.log \\
        --root ~/maaend --probe --sock /run/user/1000/wayland-1

    # 3) 机器可解析输出
    python3 web/linux/homesrv/diagnose_essence.py --log ~/maaend/essence.log --json

参数环境变量兜底：`MAAEND_ESSENCE_LOG` / `MAAEND_ROOT` / `MAAEND_OFFICIAL` / `MAAEND_SOCK`。

退出码
------
0  未发现静态缺陷（日志侧结论见 JSON 的 evidence_class）
1  有告警：日志/环境类问题（含「日志早于代码部署」）
2  有静态阻断项：官方云层节点缺失/字段不一致
3  用法或环境错误（日志不存在、参数非法）
"""

import argparse
import contextlib
import itertools
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

TS_RE = re.compile(r"^\[?(?P<ts>\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d\.\d+)\]?")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MSG_RE = re.compile(r"\[msg=(?P<msg>[A-Za-z0-9_.]+)\]")
CAPACITY_PREFIX = "AutoEssenceCapacity"
NAV_NODE_PREFIX = "GotoTriggerPoint"
CAPACITY_VERDICT_NODES = (
    "AutoEssenceCapacityBatchReady",
    "AutoEssenceCapacityCannotReach",
    "AutoEssenceCapacityNothingLeft",
)

# 官方云层专有、云画面延迟下必须补的节点；缺任一即为静态阻断项。
REQUIRED_CLOUD_NODES = {
    "AutoEssenceCapacityClickSave": "官方云层把 next 改为只等 SaveClosed",
    "AutoEssenceCapacitySaveClosed": "官方云层新增：确认筛选弹窗已关再读已选择数量",
}

PROBE_NODES = [
    "AutoEssenceCapacitySelectedCountOCR",
    "AutoEssenceCapacityCountOCR",
    "AutoEssenceCapacityDecomposePrompt",
    "AutoEssenceCapacityClickSave",
]

# 代码落地的关键路径：日志早于它们的最晚 mtime 即视为旧部署观测。
CODE_MARKERS = (
    "web/linux/run_daily_linux.py",
    "web/linux/maaend_web",
    "web/resource_web/pipeline/nodes.json",
    "web/resource_web_homesrv/pipeline/nodes.json",
)


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _decode(path):
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def load_jsonc(path):
    """容忍 // 与 /* */ 注释的 JSON 读取（仓库 pipeline 是 JSONC）。"""
    text = _decode(path)
    out = []
    i = 0
    in_str = False
    esc = False
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def _ts_delta(a, b):
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    try:
        return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds()
    except (ValueError, TypeError):
        return None


def parse_log(path):
    """把 maafw 日志压成「节点事件序列 + 关注告警 + 静默间隔」。"""
    text = ANSI_RE.sub("", _decode(path))
    events = []
    counters = {"EmptyRect": [], "TaskTimeout": [], "NotFound": [], "OcrSize": [], "InvalidNodeId": []}
    for line in text.splitlines():
        m = TS_RE.match(line)
        if not m:
            continue
        ts = m.group("ts").replace("T", " ")
        rest = line[m.end():]
        msg = MSG_RE.search(rest)
        if msg and msg.group("msg").startswith("Node.PipelineNode."):
            detail = None
            idx = rest.find("[details=")
            if idx >= 0:
                try:
                    detail, _end = json.JSONDecoder().raw_decode(rest[idx + len("[details="):])
                except ValueError:
                    detail = None
            if isinstance(detail, dict):
                node = (detail.get("node_details") or {}).get("name") or detail.get("name")
                act = detail.get("action_details") or {}
                events.append(
                    {
                        "ts": ts,
                        "kind": msg.group("msg").split(".")[-1],
                        "node": node,
                        "action": act.get("name"),
                        "action_type": act.get("action"),
                        "success": bool(act.get("success", msg.group("msg").endswith("Succeeded"))),
                        "task_id": detail.get("task_id"),
                    }
                )
            continue
        low = line.lower()
        if "custom action target rect is empty" in line:
            counters["EmptyRect"].append({"ts": ts, "line": line[-200:]})
        elif "task timeout" in low and "pretask.name=" in line:
            counters["TaskTimeout"].append({"ts": ts, "line": line[-240:]})
        elif "task not found" in low:
            counters["NotFound"].append({"ts": ts, "line": line[-160:]})
        elif "wrong ocr_result size" in low:
            counters["OcrSize"].append({"ts": ts, "line": line[-160:]})
        elif "invalid node id" in low:
            counters["InvalidNodeId"].append({"ts": ts, "line": line[-160:]})

    return {
        "events": events,
        "counters": {k: len(v) for k, v in counters.items()},
        "samples": {k: v[:3] for k, v in counters.items() if v},
    }


def analyze_chain(events, max_gap_s):
    """还原 AutoEssence 关键阶段到达情况、失败点与走位尝试窗口。

    走位窗口用「同一 task 内上一个事件 → 本次 Failed/Succeeded」度量：pipeline 不为嵌套节点发
    Node.PipelineNode.Starting，所以窗口起点只能取上一个完成事件（通常是 MaybeTeleport 的 Succeeded）。
    """
    reached = {
        "nav_move": False,
        "battle": False,
        "capacity": False,
        "capacity_click_save": False,
        "capacity_verdict": False,
    }
    verdict_hits = []
    failures = []
    nav_windows = []
    gaps = []
    by_task = {}
    for ev in events:
        by_task.setdefault(ev["task_id"], []).append(ev)
    for task_id, seq in by_task.items():
        for idx, ev in enumerate(seq):
            node = ev.get("node") or ""
            if node.startswith(CAPACITY_PREFIX):
                reached["capacity"] = True
                if node == "AutoEssenceCapacityClickSave":
                    reached["capacity_click_save"] = True
                if node in CAPACITY_VERDICT_NODES:
                    reached["capacity_verdict"] = True
                    verdict_hits.append({"ts": ev["ts"], "node": node, "success": ev["success"]})
            if node.startswith(("AutoFight", "AutoEssenceBattle", "EssenceBattle")):
                reached["battle"] = True
            if ev["kind"] == "Failed":
                failures.append({"ts": ev["ts"], "node": node, "task_id": ev["task_id"]})
            if not node.startswith(NAV_NODE_PREFIX) or ev["kind"] not in ("Failed", "Succeeded"):
                continue
            reached["nav_move"] = True
            prev = seq[idx - 1] if idx > 0 else None
            dur = _ts_delta(prev["ts"], ev["ts"]) if prev else None
            inner = seq[max(0, idx - 40):idx + 1]
            inner_gaps = []
            for a, b in itertools.pairwise(inner):
                delta = _ts_delta(a["ts"], b["ts"])
                if delta is not None and delta >= max_gap_s:
                    inner_gaps.append({"gap_s": round(delta, 1), "from_ts": a["ts"], "to_ts": b["ts"]})
                    gaps.append(
                        {
                            "task_id": task_id,
                            "node": node,
                            "gap_s": round(delta, 1),
                            "from_ts": a["ts"],
                            "from_node": a.get("node"),
                            "to_ts": b["ts"],
                            "to_node": b.get("node"),
                        }
                    )
            nav_windows.append(
                {
                    "node": node,
                    "result": ev["kind"],
                    "prev_ts": prev["ts"] if prev else None,
                    "prev_node": prev.get("node") if prev else None,
                    "end_ts": ev["ts"],
                    "duration_s": round(dur, 1) if dur is not None else None,
                    "silent_gaps": inner_gaps,
                    "navigator_subtasks": sorted(
                        {
                            x.get("node")
                            for x in inner
                            if (x.get("node") or "").startswith(("MapNavigator", "__MapNavigator"))
                        }
                    ),
                    "task_id": task_id,
                }
            )
    # 全局静默：cpp-algo 的子任务各占一个 task_id，按 task 分组会漏掉「换 task 后彻底没动静」。
    # 这里对每个走位窗口，在**全时间线**上重算区间内的最大相邻间隔。
    ordered = sorted(events, key=lambda e: e["ts"])
    stamps = [e["ts"] for e in ordered]
    for win in nav_windows:
        lo = win["prev_ts"]
        hi = win["end_ts"]
        if not lo or not hi:
            continue
        inside = [(stamps[i - 1], stamps[i]) for i in range(1, len(stamps))
                  if lo <= stamps[i - 1] and stamps[i] <= hi]
        if not inside:
            win["global_max_gap_s"] = win["duration_s"]
            continue
        best = max(inside, key=lambda pair: _ts_delta(pair[0], pair[1]) or 0)
        delta = _ts_delta(best[0], best[1]) or 0
        win["global_max_gap_s"] = round(delta, 1)
        if delta >= max_gap_s:
            gaps.append({"task_id": win["task_id"], "node": win["node"], "gap_s": round(delta, 1),
                         "from_ts": best[0], "from_node": "any", "to_ts": best[1], "to_node": "any"})

    dedup = {}
    for gap in gaps:
        dedup[(gap["task_id"], gap["from_ts"], gap["to_ts"])] = gap
    gaps = sorted(dedup.values(), key=lambda g: -g["gap_s"])
    nav_windows.sort(key=lambda w: w["end_ts"] or "")
    return {
        "reached": reached,
        "failures": failures,
        "nav_windows": nav_windows,
        "gaps": gaps,
        "capacity_verdict_hits": verdict_hits,
    }


def _iter_nodes(pipeline_dir):
    for path in sorted(Path(pipeline_dir).rglob("*.json")):
        try:
            data = load_jsonc(path)
        except Exception:
            continue
        if isinstance(data, dict):
            yield path, data


def _collect(directory):
    """{节点名: 相对文件} + 文件集合；兼容部署态的单文件 nodes.json。"""
    nodes = {}
    files = set()
    base = Path(directory)
    for path, data in _iter_nodes(base):
        rel = str(path.relative_to(base)).replace("\\", "/")
        files.add(rel)
        for key in data:
            nodes.setdefault(key, rel)
    return nodes, files


def _cloud_layers(root):
    """我们的云层候选目录，按 attach 顺序（浅 → 深）：改名后的 resource_cloud 与网页薄覆盖层。"""
    return [
        ("resource_cloud", Path(root) / "assets" / "resource_cloud" / "pipeline"),
        ("resource_cloud(old-name)", Path(root) / "assets" / "resource_cloud_adb" / "pipeline"),
        ("resource_cloud_web", Path(root) / "assets" / "resource_cloud_web" / "pipeline"),
        # 部署布局：资源层直接被摊到根目录（lib.sh:110-127）
        ("resource_cloud(deploy)", Path(root) / "resource_cloud" / "pipeline"),
        ("resource_cloud_web(deploy)", Path(root) / "resource_cloud_web" / "pipeline"),
        ("resource_web", Path(root) / "web" / "resource_web" / "pipeline"),
        ("resource_web_homesrv", Path(root) / "web" / "resource_web_homesrv" / "pipeline"),
    ]


def diff_cloud_layer(root, official, subtree="AutoEssence"):
    """对比「我们的云层并集」与官方 resource_cloud 的文件/节点/字段差集，并找出跨层冲突。

    并集而非单层：官方节点可能落在 resource_cloud 或网页薄覆盖层 resource_cloud_web 里。
    冲突单独报：同名节点被两层各定义一份时，深层整份覆盖浅层，浅层的修复会被静默盖掉。
    """
    layers = [(name, path) for name, path in _cloud_layers(root) if path.is_dir()]
    off_dir = next(
        (
            d
            for d in (
                Path(official) / "assets" / "resource_cloud" / "pipeline",
                Path(official) / "resource_cloud" / "pipeline",
            )
            if d.is_dir()
        ),
        None,
    )
    if off_dir is None:
        return {"available": False, "reason": "未找到官方 resource_cloud/pipeline（--official 应指向官方 worktree 根）"}
    if not layers:
        return {"available": False, "reason": "未找到我们的云层目录（resource_cloud / resource_cloud_web）"}

    off_nodes, off_files = _collect(off_dir)
    ours_nodes = {}
    ours_files = set()
    node_layers = {}
    node_bodies = {}
    for name, path in layers:
        nodes, files = _collect(path)
        ours_files |= set(files)
        for key in nodes:
            node_layers.setdefault(key, []).append(name)
            ours_nodes.setdefault(key, nodes[key])
    for name, path in layers:
        for key, rel in _collect(path)[0].items():
            try:
                body = load_jsonc(path / rel).get(key)
            except Exception:
                continue
            node_bodies.setdefault(key, []).append((name, body))

    conflicts = []
    for key, pairs in node_bodies.items():
        if len(pairs) < 2:
            continue
        if not (key.startswith(subtree) or key in REQUIRED_CLOUD_NODES):
            continue
        bodies = [body for _layer, body in pairs]
        if any(body != bodies[0] for body in bodies[1:]):
            conflicts.append(
                {
                    "node": key,
                    "layers": [layer for layer, _body in pairs],
                    "detail": "同名节点多层定义且内容不同；深层整份覆盖浅层",
                }
            )

    gate_conflicts = []
    for layer, body in node_bodies.get("AutoEssenceCapacityClickSave", []):
        nxt = (body or {}).get("next")
        if nxt and nxt != ["AutoEssenceCapacitySaveClosed"]:
            gate_conflicts.append({"layer": layer, "next": nxt})

    field_diffs = []
    for rel in sorted(off_files):
        for name, path in layers:
            ours_path = path / rel
            if not ours_path.is_file():
                continue
            try:
                off_data = load_jsonc(off_dir / rel)
                ours_data = load_jsonc(ours_path)
            except Exception:
                continue
            changed = [n for n in off_data if n in ours_data and ours_data[n] != off_data[n]]
            if changed:
                field_diffs.append({"file": rel, "layer": name, "nodes": sorted(changed)})
            break

    missing_nodes = sorted(set(off_nodes) - set(ours_nodes))
    return {
        "available": True,
        "layers": [{"name": name, "dir": str(path)} for name, path in layers],
        "official_dir": str(off_dir),
        "file_only_official": sorted(off_files - ours_files),
        "file_only_ours": sorted(ours_files - off_files),
        "node_only_official": missing_nodes,
        "node_only_official_in_subtree": [n for n in missing_nodes if off_nodes[n].startswith(subtree + "/")],
        "required_cloud_nodes_absent": [n for n in REQUIRED_CLOUD_NODES if n not in ours_nodes],
        "required_cloud_node_layers": {n: node_layers.get(n, []) for n in REQUIRED_CLOUD_NODES},
        "field_diffs": field_diffs,
        "cross_layer_conflicts": conflicts,
        "gate_override_conflicts": gate_conflicts,
    }


def deploy_layers(root):
    """按 homesrv lib.sh:110-127 的 mh_res_dirs 规则算出「部署机上真正会加载」的层序。

    两个容易踩的点：
    - `resource_cloud` 是「官方云层，新版本才发」，缺失时 `|| true` 静默跳过；
    - `resource_cloud_web` 一旦存在，`web/resource_web` 与 `web/resource_web_homesrv` **不再加载**
      （它们只是兜底），所以旧覆盖层的节点会整体消失。
    """
    root = Path(root)
    if not (root / "resource").is_dir():
        return {"available": False, "reason": "不是部署布局（缺 <root>/resource）"}
    effective = []
    skipped = []
    if (root / "resource").is_dir():
        effective.append("resource")
    if (root / "resource_cloud").is_dir():
        effective.append("resource_cloud")
    else:
        skipped.append({"layer": "resource_cloud", "reason": "缺失（官方云层随新版发行包才带）"})
    if (root / "resource_cloud_web").is_dir():
        effective.append("resource_cloud_web")
        for name in ("web/resource_web", "web/resource_web_homesrv"):
            if (root / name).is_dir():
                skipped.append({"layer": name, "reason": "resource_cloud_web 已存在，旧覆盖层不再加载"})
    else:
        for name in ("web/resource_web", "web/resource_web_homesrv"):
            if (root / name).is_dir():
                effective.append(name)
    if (root / "web/linux/resource_web_linux").is_dir():
        effective.append("web/linux/resource_web_linux")

    gate = {}
    for node in REQUIRED_CLOUD_NODES:
        matches = []
        for name in effective:
            directory = root / name / "pipeline"
            if not directory.is_dir():
                continue
            nodes, _files = _collect(directory)
            if node in nodes:
                matches.append({"layer": name, "file": nodes[node]})
        winner = matches[-1] if matches else None
        detail = {"matches": matches, "winner": winner, "next": None, "gate_effective": None}
        if winner and node == "AutoEssenceCapacityClickSave":
            try:
                body = load_jsonc(root / winner["layer"] / "pipeline" / winner["file"]).get(node) or {}
            except Exception:
                body = {}
            detail["next"] = body.get("next")
            detail["gate_effective"] = body.get("next") == ["AutoEssenceCapacitySaveClosed"]
        gate[node] = detail
    return {"available": True, "effective": effective, "skipped": skipped, "required_nodes": gate}


def find_base_capacity(repo):
    """定位 base 层 AutoEssenceCapacityClickSave（仓库分文件 & 部署态合并 nodes.json 都认）。"""
    candidates = [
        Path(repo) / "assets" / "resource" / "pipeline" / "AutoEssence" / "CommonNodes" / "Capacity.json",
        Path(repo) / "resource" / "pipeline" / "AutoEssence" / "CommonNodes" / "Capacity.json",
        Path(repo) / "resource" / "pipeline" / "nodes.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = load_jsonc(path)
        except Exception:
            continue
        if not isinstance(data, dict) or "AutoEssenceCapacityClickSave" not in data:
            continue
        save = data.get("AutoEssenceCapacityClickSave") or {}
        return {
            "path": str(path),
            "merged": path.name == "nodes.json",
            "click_save_next": (save.get("next") or []),
            "post_wait_freezes": save.get("post_wait_freezes"),
            "has_save_closed": "AutoEssenceCapacitySaveClosed" in data,
            "verdict_nodes_present": [n for n in CAPACITY_VERDICT_NODES if n in data],
        }
    return {"path": None}


def code_epoch(repo):
    """代码落地的可判定时间：关键路径的最晚 mtime。"""
    stamps = []
    for rel in CODE_MARKERS:
        path = Path(repo) / rel
        if path.is_file():
            stamps.append(path.stat().st_mtime)
        elif path.is_dir():
            for child in path.rglob("*.py"):
                stamps.append(child.stat().st_mtime)
    if not stamps:
        return None
    return datetime.fromtimestamp(max(stamps)).isoformat(timespec="seconds")


def probe_readonly(sock, dirs, nodes, log_dir):
    """只读评分：一次截图，对指定节点逐个跑识别。不发任何输入。"""
    if not sock:
        return {"ok": False, "error": "缺少 --sock（WlRoots socket 路径）"}
    try:
        from maa.controller import WlRootsController
        from maa.pipeline import JAnd, JRecognitionType
        from maa.resource import Resource
        from maa.tasker import Tasker
    except Exception as exc:  # pragma: no cover - 依赖运行环境
        return {"ok": False, "error": "无法 import maa：%s" % exc}

    res = Resource()
    loaded = []
    for directory in dirs:
        if directory and Path(directory).is_dir():
            res.post_bundle(str(directory)).wait()
            loaded.append(str(directory))
    ctrl = WlRootsController(sock, use_win32_vk_code=True)
    ctrl.post_connection().wait()
    tasker = Tasker()
    tasker.bind(res, ctrl)
    if log_dir:
        with contextlib.suppress(Exception):
            tasker.set_log_dir(str(log_dir))
    ctrl.post_screencap().wait()
    img = ctrl.cached_image
    if img is None:
        return {"ok": False, "error": "screencap 失败（无缓存帧）", "loaded": loaded}
    shot = Path(log_dir or ".") / "diagnose_essence_probe.png"
    try:
        if hasattr(img, "save"):
            img.save(str(shot))
    except Exception:
        shot = None
    out = {"ok": True, "loaded": loaded, "screenshot": str(shot) if shot else None, "nodes": {}}
    for node in nodes:
        try:
            job = tasker.post_recognition(JRecognitionType.And, JAnd(all_of=[node]), img)
            job.wait()
            detail = job.get()
            ids = list(getattr(detail, "node_id_list", None) or [])
            if not ids:
                out["nodes"][node] = {"hit": None, "note": "未产生节点详情（节点不存在或未加载）"}
                continue
            rd = tasker.get_node_detail(int(ids[0])).recognition
            rec = {"hit": bool(getattr(rd, "hit", False)), "box": getattr(rd, "box", None)}
            det = getattr(rd, "detail", None)
            texts = []
            if isinstance(det, dict):
                for item in det.get("all") or []:
                    if isinstance(item, dict) and item.get("text"):
                        texts.append({"text": item["text"], "score": item.get("score")})
            if texts:
                rec["ocr"] = texts[:8]
            out["nodes"][node] = rec
        except Exception as exc:
            out["nodes"][node] = {"error": str(exc)}
    return out


def build_findings(analysis, diff, base_capacity, stale, gaps, layers_report):
    """每条发现都带 evidence_class：static=代码级可证 / log=日志观测 / needs-live=需实机复验。"""
    findings = []
    if diff.get("available"):
        absent = diff.get("required_cloud_nodes_absent") or []
        if absent:
            findings.append(
                {
                    "id": "E-CAP-CLOUD-GATE",
                    "severity": "blocking",
                    "evidence_class": "static",
                    "title": "云层缺少官方 AutoEssence 容量门控节点：%s" % "、".join(absent),
                    "evidence": "官方 %s/AutoEssence/CommonNodes/Capacity.json 的 2 个节点；"
                    "我们云层（%s）差集为 %s；base 的 AutoEssenceCapacityClickSave.next=%s"
                    % (
                        diff["official_dir"],
                        ", ".join(x["name"] for x in diff.get("layers") or []),
                        absent,
                        json.dumps(base_capacity.get("click_save_next"), ensure_ascii=False),
                    ),
                    "impact": "云画面延迟下点保存后仍隔着筛选弹窗读「已选择 0/200」，"
                    "→ AutoEssenceCapacityNothingLeft/CannotReach 命中 → 本轮不分解直接退出，产出 0。",
                    "fix_scope": "只补云层 pipeline 数据（不碰 base），sa-1 名下。",
                }
            )
        for conflict in diff.get("gate_override_conflicts") or []:
            findings.append(
                {
                    "id": "E-GATE-OVERRIDDEN",
                    "severity": "blocking",
                    "evidence_class": "static",
                    "title": "AutoEssenceCapacityClickSave 被 %s 层改回直连三个判定节点" % conflict["layer"],
                    "evidence": "该层 next=%s，云层门控 AutoEssenceCapacitySaveClosed 被整份覆盖"
                    % json.dumps(conflict["next"], ensure_ascii=False),
                    "impact": "等于没补官方门控：点保存后仍会隔着筛选弹窗读到「已选择 0/200」。",
                }
            )
        for conflict in diff.get("cross_layer_conflicts") or []:
            findings.append(
                {
                    "id": "E-CLOUD-LAYER-CONFLICT",
                    "severity": "warn",
                    "evidence_class": "static",
                    "title": "同名节点多层定义且内容不同：%s" % conflict["node"],
                    "evidence": "层 %s；%s" % (", ".join(conflict["layers"]), conflict["detail"]),
                }
            )
        if diff.get("field_diffs"):
            findings.append(
                {
                    "id": "E-CLOUD-FIELD-DIFF",
                    "severity": "warn",
                    "evidence_class": "static",
                    "title": "云层与官方同文件字段不一致：%s"
                    % ", ".join(f["file"] for f in diff["field_diffs"]),
                    "evidence": "见 cloud_layer_diff.field_diffs",
                }
            )
    if layers_report.get("available"):
        gate = layers_report.get("required_nodes") or {}
        absent = [n for n, detail in gate.items() if not detail.get("winner")]
        if gate.get("AutoEssenceCapacitySaveClosed", {}).get("winner") is None:
            absent = sorted(set(absent) | {"AutoEssenceCapacitySaveClosed"})
        click_save = gate.get("AutoEssenceCapacityClickSave") or {}
        if click_save.get("winner") and click_save.get("gate_effective") is False:
            findings.append(
                {
                    "id": "E-DEPLOY-GATE-NEUTRALIZED",
                    "severity": "blocking",
                    "evidence_class": "static",
                    "title": "部署机上 AutoEssenceCapacityClickSave 的生效定义仍直连三个判定节点",
                    "evidence": "生效层 %s 的 next=%s（期望 [AutoEssenceCapacitySaveClosed]）；"
                    "命中层序 %s" % (
                        click_save["winner"]["layer"],
                        json.dumps(click_save.get("next"), ensure_ascii=False),
                        [m["layer"] for m in click_save.get("matches") or []]),
                    "impact": "仓库里补了门控，但被更深的层整份覆盖回去，等于没补。",
                }
            )
        if absent:
            findings.append(
                {
                    "id": "E-DEPLOY-GATE-ABSENT",
                    "severity": "blocking",
                    "evidence_class": "static",
                    "title": "部署机上这两个节点找不到：%s" % "、".join(absent),
                    "evidence": "有效加载层 %s；跳过 %s" % (
                        layers_report["effective"],
                        [x["layer"] for x in layers_report["skipped"]]),
                    "impact": "仓库里有、线上没加载 = 门控等于没生效。",
                }
            )
        for item in layers_report.get("skipped") or []:
            findings.append(
                {
                    "id": "E-DEPLOY-LAYER-SKIP",
                    "severity": "warn",
                    "evidence_class": "static",
                    "title": "层 %s 不会被加载：%s" % (item["layer"], item["reason"]),
                    "evidence": "lib.sh:110-127 的 mh_res_dirs 兜底规则",
                }
            )
    if base_capacity.get("path") and base_capacity.get("merged"):
        findings.append(
            {
                "id": "E-DEPLOY-MERGED-PIPELINE",
                "severity": "info",
                "evidence_class": "static",
                "title": "部署态 base 是单文件 nodes.json（覆盖层仍在 web/resource_web/pipeline）",
                "evidence": base_capacity["path"] + " 内含 AutoEssenceCapacityClickSave；"
                "覆盖层节点不在此文件，缺覆盖层时会出现 invalid node id",
            }
        )
    if stale:
        findings.append(
            {
                "id": "E-STALE-LOG",
                "severity": "warn",
                "evidence_class": "log",
                "title": "日志末条时间早于当前代码部署时间，其中的失败不能当作当前代码的证据",
                "evidence": "日志末条 %s / 代码 mtime %s" % (stale["log_last_ts"], stale["code_epoch"]),
            }
        )
    nav_failed = [w for w in analysis["nav_windows"] if w["result"] == "Failed"]
    if nav_failed:
        findings.append(
            {
                "id": "E-NAV-FAILED",
                "severity": "warn" if stale else "blocking",
                "evidence_class": "log",
                "title": "日志中出现 GotoTriggerPoint* 走位失败（%d 次）" % len(nav_failed),
                "evidence": "；".join(
                    "%s %s→%s 用时 %ss" % (w["node"], w["prev_ts"], w["end_ts"], w["duration_s"])
                    for w in nav_failed[:4]
                )
                + ("（旧部署观测，需复验）" if stale else ""),
            }
        )
    if gaps:
        top = gaps[0]
        findings.append(
            {
                "id": "E-SILENT-GAP",
                "severity": "warn",
                "evidence_class": "log",
                "title": "task 内出现 %.1fs 无事件静默（%s → %s）" % (top["gap_s"], top["from_node"], top["to_node"]),
                "evidence": "%s → %s，task_id=%s；essence.log 不含 cpp-algo 内部行，"
                "该窗口内的决策只能从 cpp-algo 日志（debug/cpp-algo/debug）取"
                % (top["from_ts"], top["to_ts"], top["task_id"]),
            }
        )
    if analysis["counters"].get("TaskTimeout"):
        findings.append(
            {
                "id": "E-RECO-TIMEOUT",
                "severity": "warn",
                "evidence_class": "log",
                "title": "出现 next 列表 20s reco_timeout，会把失败归因到错误节点",
                "evidence": "Task timeout 行 %d 条" % analysis["counters"]["TaskTimeout"],
            }
        )
    if not analysis["reached"]["capacity"] and analysis.get("has_events"):
        findings.append(
            {
                "id": "E-CAPACITY-NOT-REACHED",
                "severity": "info",
                "evidence_class": "log",
                "title": "本日志未进入容量检查阶段，容量缺陷无法由本日志复现（需先修走位或直接跑该阶段）",
                "evidence": "AutoEssenceCapacity* 节点命中 0 次",
            }
        )
    if not analysis.get("has_events"):
        findings.append(
            {
                "id": "E-NO-EVENTS",
                "severity": "warn",
                "evidence_class": "needs-live",
                "title": "日志里没有解析到 Node.PipelineNode.* 事件",
                "evidence": "确认 --log 指向 maafw 日志（essence.log 由脚本 exec >>LOG 2>&1 收集）",
            }
        )
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="AutoEssence 只读诊断（日志 + 云层差集 + 可选只读评分）")
    ap.add_argument("--log", action="append", default=[], help="essence.log 路径，可重复")
    ap.add_argument("--root", default=os.environ.get("MAAEND_ROOT", "~/maaend"), help="部署/仓库根")
    ap.add_argument("--repo", default=None, help="源码树根（缺省同 --root）")
    ap.add_argument("--official", default=os.environ.get("MAAEND_OFFICIAL", ""), help="官方 worktree 根")
    ap.add_argument("--max-gap", type=float, default=20.0, help="静默间隔阈值（秒）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--json-out", default="", help="把 JSON 另存到该路径")
    ap.add_argument("--probe", action="store_true", help="追加一次只读截图识别评分")
    ap.add_argument("--sock", default=os.environ.get("MAAEND_SOCK", ""), help="WlRoots socket（probe 用）")
    ap.add_argument("--log-dir", default="", help="probe 时 tasker 日志/截图目录")
    args = ap.parse_args(argv)

    logs = [Path(p).expanduser() for p in args.log]
    if not logs:
        env_log = os.environ.get("MAAEND_ESSENCE_LOG")
        if env_log:
            logs = [Path(env_log).expanduser()]
        else:
            for cand in ("~/maaend/essence.log", "~/maaend/nightly.log"):
                path = Path(cand).expanduser()
                if path.is_file():
                    logs = [path]
                    break
    missing = [str(p) for p in logs if not p.is_file()]
    logs = [p for p in logs if p.is_file()]
    if not logs:
        print("错误：找不到日志。用 --log 指定，或设 MAAEND_ESSENCE_LOG。", file=sys.stderr)
        if missing:
            print("  不存在：%s" % ", ".join(missing), file=sys.stderr)
        return 3

    root = Path(args.root).expanduser()
    repo = Path(args.repo).expanduser() if args.repo else root
    if not root.is_dir():
        print("错误：--root 不是目录：%s" % root, file=sys.stderr)
        return 3

    events = []
    counters = {}
    samples = {}
    for path in logs:
        part = parse_log(path)
        events.extend(part["events"])
        for key, value in part["counters"].items():
            counters[key] = counters.get(key, 0) + value
        for key, value in part["samples"].items():
            samples.setdefault(key, []).extend(value)

    analysis = analyze_chain(events, args.max_gap)
    analysis["counters"] = counters
    analysis["has_events"] = bool(events)

    epoch = code_epoch(repo)
    log_last = events[-1]["ts"] if events else None
    stale = None
    if epoch and log_last:
        try:
            if datetime.strptime(log_last, "%Y-%m-%d %H:%M:%S.%f") < datetime.fromisoformat(epoch):
                stale = {"log_last_ts": log_last, "code_epoch": epoch}
        except ValueError:
            stale = None

    base_capacity = find_base_capacity(repo)
    layers_report = deploy_layers(root)
    diff = {"available": False, "reason": "未指定 --official"}
    if args.official and Path(args.official).expanduser().is_dir():
        diff = diff_cloud_layer(root, Path(args.official).expanduser())

    probe = None
    if args.probe:
        dirs = [
            root / "resource",
            root / "assets" / "resource",
            root / "web" / "resource_web",
            root / "web" / "linux" / "resource_web_linux",
        ]
        probe = probe_readonly(
            args.sock, dirs, PROBE_NODES, args.log_dir or str(Path.home() / "maaend-log")
        )

    gaps = analysis["gaps"]
    findings = build_findings(analysis, diff, base_capacity, stale, gaps, layers_report)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    warn = [f for f in findings if f["severity"] == "warn"]
    report = {
        "generated_at": _now(),
        "tool": "diagnose_essence.py",
        "inputs": {
            "logs": [str(p) for p in logs],
            "root": str(root),
            "repo": str(repo),
            "official": args.official or None,
            "max_gap_s": args.max_gap,
        },
        "freshness": {
            "code_epoch": epoch,
            "log_last_ts": log_last,
            "log_precedes_code": bool(stale),
        },
        "timeline": {
            "node_events": len(events),
            "first_ts": events[0]["ts"] if events else None,
            "last_ts": log_last,
            "top_gaps": gaps[:5],
            "counters": counters,
            "samples": samples,
        },
        "chain": analysis,
        "base_capacity": base_capacity,
        "deploy_layers": layers_report,
        "cloud_layer_diff": diff,
        "probe": probe,
        "findings": findings,
        "verdict": {
            "static_blocking": [f["id"] for f in blocking if f["evidence_class"] == "static"],
            "warnings": [f["id"] for f in warn],
            "needs_live_verification": True,
            "exit_code": 2 if blocking else (1 if warn else 0),
        },
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).expanduser().write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
    else:
        _print_human(report)
    return report["verdict"]["exit_code"]


def _print_human(report):
    print("== AutoEssence 只读诊断 ==")
    print("日志     : %s" % ", ".join(report["inputs"]["logs"]))
    fresh = report["freshness"]
    print("新鲜度   : 代码 mtime=%s 日志末条=%s → %s" % (
        fresh["code_epoch"], fresh["log_last_ts"],
        "日志早于代码部署，仅作历史参考" if fresh["log_precedes_code"] else "同一代代码"))
    print("节点事件 : %d 条（%s → %s）" % (
        report["timeline"]["node_events"], report["timeline"]["first_ts"], report["timeline"]["last_ts"]))
    reached = report["chain"]["reached"]
    print("阶段到达 : 走位=%s 战斗=%s 容量=%s 容量判定=%s" % (
        reached["nav_move"], reached["battle"], reached["capacity"], reached["capacity_verdict"]))
    base = report["base_capacity"]
    if base.get("path"):
        print("base 容量: %s%s" % (base["path"], "（部署态合并文件）" if base.get("merged") else ""))
        print("  ClickSave.next = %s" % json.dumps(base["click_save_next"], ensure_ascii=False))
        print("  post_wait_freezes = %s" % json.dumps(base.get("post_wait_freezes"), ensure_ascii=False))
    layers = report.get("deploy_layers") or {}
    if layers.get("available"):
        print("部署层序 : %s" % " → ".join(layers["effective"]))
        print("  门控节点: %s" % json.dumps(layers["required_nodes"], ensure_ascii=False))
    diff = report["cloud_layer_diff"]
    if diff.get("available"):
        print("云层     : %s" % ", ".join("%s(%s)" % (x["name"], x["dir"]) for x in diff["layers"]))
        print("云层差集 : 仅官方有的文件 %d 个 / 节点 %d 个" % (
            len(diff["file_only_official"]), len(diff["node_only_official"])))
        print("  门控节点所在层: %s" % json.dumps(diff.get("required_cloud_node_layers"), ensure_ascii=False))
        if diff["file_only_official"]:
            print("  文件: %s" % ", ".join(diff["file_only_official"]))
        print("  AutoEssence 子树缺: %s" % (diff["node_only_official_in_subtree"] or "无"))
        print("  必补节点缺: %s" % (diff["required_cloud_nodes_absent"] or "无"))
        if diff["field_diffs"]:
            print("  同文件字段差异: %s" % ", ".join(f["file"] for f in diff["field_diffs"]))
    else:
        print("云层差集 : 跳过（%s）" % diff.get("reason"))
    if report["timeline"]["top_gaps"]:
        print("静默间隔 :")
        for gap in report["timeline"]["top_gaps"]:
            print("  %6.1fs  %-28s → %-28s (%s → %s)" % (
                gap["gap_s"], gap["from_node"], gap["to_node"], gap["from_ts"], gap["to_ts"]))
    if report["chain"]["nav_windows"]:
        print("走位窗口 :")
        for win in report["chain"]["nav_windows"]:
            print("  %-34s %-9s %7s  窗口内最大静默 %-6s %s → %s" % (
                win["node"], win["result"],
                "-" if win["duration_s"] is None else "%.1fs" % win["duration_s"],
                "-" if win.get("global_max_gap_s") is None else "%.1fs" % win["global_max_gap_s"],
                win["prev_ts"] or "-", win["end_ts"]))
    print("结论     :")
    for item in report["findings"]:
        print("  [%-8s][%-10s] %-20s %s" % (
            item["severity"], item["evidence_class"], item["id"], item["title"]))
        print("      依据: %s" % item["evidence"])
        if item.get("impact"):
            print("      影响: %s" % item["impact"])
    if report["probe"]:
        print("只读评分 : %s" % json.dumps(report["probe"].get("nodes", report["probe"]),
                                          ensure_ascii=False)[:800])
    print("退出码   : %d" % report["verdict"]["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
