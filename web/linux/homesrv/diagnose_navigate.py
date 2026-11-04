#!/usr/bin/env python3
"""走位链只读诊断：MapNavigateAction / GotoTriggerPoint* 的日志窗口 + 静态前置条件核对。

背景
----
云·终末地（Linux 网页端）的基质链卡在 `GotoTriggerPointMove_<Region>`：`MapNavigateAction` 启动后
长时间没有任何事件，最后 `Node.PipelineNode.Failed`。而 `essence.log` 只收 maafw 的行（cpp-algo
写自己的 `debug/cpp-algo/debug`），所以「导航内部为什么失败」在 essence.log 里**根本不存在**。
本脚本做两件事：

1. 用日志把窗口钉死：起点、终点、时长、窗口内出现过哪些 MapNavigator 子任务、最长静默在哪。
2. 用静态核对把可证伪的前置条件排掉：部署的 cpp-algo 二进制是否 1.0856 版（转向系数 3.86 units/度）、
   `base.nav.gz` 是否在、路线里声明的 zone 是否在 navmesh 里、路线引用的 interact 节点是否加载得到、
   cpp-algo 自己的日志目录是否有内容。

只读边界
--------
不点击、不按键、不派发任务。`--probe` 只做一次 `post_screencap` + `post_recognition` 评分。
默认纯离线。

用法
----
    # 1) 纯离线：日志窗口 + 静态核对
    python3 web/linux/homesrv/diagnose_navigate.py \\
        --log ~/maaend/essence.log --root ~/maaend --repo ~/maaend \\
        --node GotoTriggerPointMove_VFTheHub

    # 2) 追加只读评分（当前画面里小地图/交互提示的命中情况）
    python3 web/linux/homesrv/diagnose_navigate.py --log ~/maaend/essence.log \\
        --root ~/maaend --probe --sock /run/user/1000/wayland-1

    # 3) 机器可解析
    python3 web/linux/homesrv/diagnose_navigate.py --log ~/maaend/essence.log --json

环境变量兜底：`MAAEND_ESSENCE_LOG` / `MAAEND_ROOT` / `MAAEND_SOCK`。

退出码
------
0  静态前置条件齐全、日志窗口无异常
1  有告警（旧部署日志、cpp-algo 日志缺失、静默窗口等）
2  静态前置条件不满足（二进制 md5 不符 / navmesh 缺 zone / 路线引用节点缺失）
3  用法或环境错误
"""

import argparse
import contextlib
import gzip
import hashlib
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

# auto_update.sh 里钉死的 1.0856 版 cpp-algo（3.86 units/度）。部署态必须与它一致。
DEFAULT_EXPECT_MD5 = "4056272952b61fe10a9e0a0e7484bbf5"
DEFAULT_ZONE = "ValleyIV_Base"
PROBE_NODES = [
    "InMapAny",
    "InMapValleyIVTheHub",
    "__MapNavigatorObstacleDevice_InteractPre",
    "MapNavigatorInteractStart",
]
NAV_ASSET_HINTS = (
    "assets/resource/model/map/navmesh/base.nav",
    "assets/resource/model/map/navmesh/base.nav.gz",
    "resource/model/map/navmesh/base.nav",
    "resource/model/map/navmesh/base.nav.gz",
)
CODE_MARKERS = ("web/linux/run_daily_linux.py", "web/linux/maaend_web", "web/resource_web/pipeline/nodes.json")


def _decode(path):
    return Path(path).read_bytes().decode("utf-8", errors="replace")


def load_jsonc(path):
    """容忍 // 与 /* */ 注释的 JSON 读取。"""
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
    """抽 Node.* 事件（含 NextList）+ 关注告警，供窗口还原。"""
    text = ANSI_RE.sub("", _decode(path))
    events = []
    warns = []
    for line in text.splitlines():
        m = TS_RE.match(line)
        if not m:
            continue
        ts = m.group("ts").replace("T", " ")
        rest = line[m.end():]
        msg = MSG_RE.search(rest)
        if msg and msg.group("msg").startswith("Node."):
            detail = None
            idx = rest.find("[details=")
            if idx >= 0:
                try:
                    detail, _end = json.JSONDecoder().raw_decode(rest[idx + len("[details="):])
                except ValueError:
                    detail = None
            name = None
            if isinstance(detail, dict):
                name = (detail.get("node_details") or {}).get("name") or detail.get("name")
            events.append({"ts": ts, "msg": msg.group("msg"), "node": name, "task_id": (detail or {}).get("task_id")})
            continue
        if any(k in line for k in ("custom action target rect is empty", "Task timeout", "task not found",
                                   "Wrong ocr_result size", "invalid node id")):
            warns.append({"ts": ts, "line": line[-220:]})
    return {"events": events, "warns": warns}


def nav_windows(events, node_prefix, max_gap_s):
    """把每次走位尝试切成一个窗口：上一个同前缀终点（或任务起点）→ 本次 Succeeded/Failed。

    cpp-algo 的每个子任务（MapNavigatorInteractStart / MapNavigatorObstacleDevice …）各占一个
    task_id，所以窗口必须按**全局时间线**切，不能按 task_id 分组。
    """
    ordered = sorted(events, key=lambda e: e["ts"])
    terminal_ids = [
        i
        for i, ev in enumerate(ordered)
        if (ev.get("node") or "").startswith(node_prefix)
        and ev["msg"] in ("Node.PipelineNode.Succeeded", "Node.PipelineNode.Failed")
    ]
    windows = []
    for pos, idx in enumerate(terminal_ids):
        ev = ordered[idx]
        prev_idx = terminal_ids[pos - 1] if pos else max(0, idx - 1)
        if prev_idx >= idx:
            prev_idx = max(0, idx - 1)
        span = ordered[prev_idx + 1: idx + 1]
        if not span:
            continue
        duration = _ts_delta(ordered[prev_idx]["ts"], ev["ts"])
        gaps = []
        for a, b in itertools.pairwise(span):
            delta = _ts_delta(a["ts"], b["ts"])
            if delta is not None and delta >= max_gap_s:
                gaps.append({"gap_s": round(delta, 1), "from": a["ts"], "to": b["ts"],
                             "from_node": a.get("node"), "to_node": b.get("node")})
        lead = _ts_delta(ordered[prev_idx]["ts"], span[0]["ts"])
        if lead is not None and lead >= max_gap_s:
            gaps.insert(0, {"gap_s": round(lead, 1), "from": ordered[prev_idx]["ts"], "to": span[0]["ts"],
                            "from_node": ordered[prev_idx].get("node"), "to_node": span[0].get("node")})
        subtasks = sorted(
            {x.get("node") for x in span if (x.get("node") or "").startswith(("MapNavigator", "__MapNavigator"))}
        )
        windows.append(
            {
                "node": ev.get("node"),
                "result": "Failed" if ev["msg"].endswith("Failed") else "Succeeded",
                "prev_ts": ordered[prev_idx]["ts"],
                "prev_node": ordered[prev_idx].get("node"),
                "end_ts": ev["ts"],
                "duration_s": round(duration, 1) if duration is not None else None,
                "silent_gaps": gaps,
                "navigator_subtasks": subtasks,
                "nextlist_failed_retries": sum(1 for x in span if x["msg"] == "Node.NextList.Failed"),
                "events_in_window": len(span),
            }
        )
    return windows


def md5_of(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_binary(root, expect_md5):
    path = Path(root) / "agent" / "cpp-algo"
    if not path.is_file():
        return {"available": False, "path": str(path), "reason": "部署态找不到 agent/cpp-algo"}
    got = md5_of(path)
    return {
        "available": True,
        "path": str(path),
        "md5": got,
        "expect": expect_md5,
        "matches": got == expect_md5,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "size": path.stat().st_size,
    }


def source_constants(repo):
    """从源码读转向系数与关键超时；仓库里可能没有 cpp-algo（部署态只有二进制）。"""
    header = Path(repo) / "agent" / "cpp-algo" / "source" / "MapNavigator" / "navi_config.h"
    if not header.is_file():
        return {"available": False, "path": str(header)}
    text = _decode(header)

    def grab(name):
        match = re.search(r"%s\s*=\s*([A-Za-z_0-9.]+)" % name, text)
        if not match:
            return None
        value = match.group(1)
        try:
            return float(value)
        except ValueError:
            inner = re.search(r"%s\s*=\s*([0-9.]+)" % re.escape(value), text)
            return float(inner.group(1)) if inner else value

    return {
        "available": True,
        "path": str(header),
        "kTurn360UnitsPerWidth": grab("kTurn360UnitsPerWidth"),
        "kLocalizationLossTimeoutMs": grab("kLocalizationLossTimeoutMs"),
        "kDwellWatchdogFailMs": grab("kDwellWatchdogFailMs"),
        "kZoneConfirmTimeoutMs": grab("kZoneConfirmTimeoutMs"),
        "kObstacleDeviceMatchThreshold": grab("kObstacleDeviceMatchThreshold"),
        "kRecoveryDeviceAttempts": grab("kRecoveryDeviceAttempts"),
    }


def find_navmesh(root):
    for rel in NAV_ASSET_HINTS:
        path = Path(root) / rel
        if path.is_file():
            return path
    return None


def scan_zones(path, zones, max_mb):
    """在 navmesh 包里找 zone 名字（deflate 流里逐块扫，只读）。"""
    result = dict.fromkeys(zones, False)
    needles = {zone: zone.encode("utf-8") for zone in zones}
    budget = max(1, int(max_mb)) << 20
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as handle:
                read = 0
                while read < budget:
                    chunk = handle.read(1 << 22)
                    if not chunk:
                        break
                    read += len(chunk)
                    for zone, needle in needles.items():
                        if not result[zone] and needle in chunk:
                            result[zone] = True
                    if all(result.values()):
                        break
        else:
            with open(path, "rb") as handle:
                read = 0
                while read < budget:
                    chunk = handle.read(1 << 22)
                    if not chunk:
                        break
                    read += len(chunk)
                    for zone, needle in needles.items():
                        if not result[zone] and needle in chunk:
                            result[zone] = True
                    if all(result.values()):
                        break
    except Exception as exc:
        return {"error": str(exc), "zones": result}
    return {"scanned_mb": round(budget / (1 << 20), 1), "zones": result}


def _load_nodes(directory):
    nodes = {}
    base = Path(directory)
    for path in sorted(base.rglob("*.json")):
        try:
            data = load_jsonc(path)
        except Exception:
            continue
        if isinstance(data, dict):
            for key, value in data.items():
                nodes.setdefault(key, value)
    return nodes


def route_report(root, repo, node_name):
    """读路线定义：ZONE / NAVMESH / INTERACT 与引用节点是否都在已加载资源里。"""
    search_dirs = [
        Path(repo) / "assets" / "resource" / "pipeline",
        Path(repo) / "resource" / "pipeline",
        Path(root) / "assets" / "resource" / "pipeline",
        Path(root) / "resource" / "pipeline",
    ]
    loaded = {}
    defined_in = None
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        nodes = _load_nodes(directory)
        if node_name in nodes and defined_in is None:
            defined_in = str(directory)
            loaded.update(nodes)
        else:
            loaded.update(nodes)
        if defined_in:
            break
    if node_name not in loaded:
        return {"available": False, "reason": "找不到节点定义 %s（--repo/--root 是否为资源根？）" % node_name}
    body = loaded[node_name] or {}
    param = ((body.get("action") or {}).get("param") or {}).get("custom_action_param") or {}
    path = param.get("path") or []
    zones, navmesh, interacts, refs = [], [], [], []
    for point in path:
        if not isinstance(point, dict):
            continue
        action = point.get("action")
        if action == "ZONE":
            zones.append(point.get("zone_id"))
        elif action in ("NAVMESH", "RUN", "SPRINT", "JUMP"):
            navmesh.append({"action": action, "target": point.get("target"),
                            "target_tier": point.get("target_tier"),
                            "target_deck_y": point.get("target_deck_y")})
        elif action == "INTERACT":
            text = point.get("interact_text")
            text_node = text.get("node") if isinstance(text, dict) else None
            interacts.append({"target": point.get("target"), "strict_arrival": point.get("strict_arrival"),
                              "interact_text_node": text_node, "interact_scan": point.get("interact_scan"),
                              "interact_rec": point.get("interact_rec")})
            for ref in (text_node, point.get("interact_scan")):
                if ref:
                    refs.append(ref)
    missing_refs = [ref for ref in refs if ref not in loaded]
    return {
        "available": True,
        "defined_in": defined_in,
        "zones": [z for z in zones if z],
        "navmesh_points": navmesh,
        "interacts": interacts,
        "referenced_nodes": refs,
        "missing_referenced_nodes": missing_refs,
        "on_error": body.get("on_error"),
        "next": body.get("next"),
        "post_delay": body.get("post_delay"),
        "timeout": body.get("timeout"),
    }


def cpp_algo_logs(root):
    """cpp-algo 的日志目录（main.cpp 的 kLogDir=debug/cpp-algo/debug，相对 cwd）。"""
    for rel in ("debug/cpp-algo/debug", "maaend-log"):
        directory = Path(root) / rel
        if directory.is_dir():
            files = sorted(directory.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            return {
                "available": True,
                "dir": str(directory),
                "files": [
                    {"name": f.name, "size": f.stat().st_size,
                     "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")}
                    for f in files[:8] if f.is_file()
                ],
            }
    return {"available": False, "reason": "找不到 cpp-algo 日志目录（debug/cpp-algo/debug 或 maaend-log）"}


def probe_readonly(sock, dirs, nodes, log_dir):
    """只读评分：一次截图，对指定节点逐个跑识别。不发任何输入。"""
    if not sock:
        return {"ok": False, "error": "缺少 --sock（WlRoots socket 路径）"}
    try:
        from maa.controller import WlRootsController
        from maa.pipeline import JAnd, JRecognitionType
        from maa.resource import Resource
        from maa.tasker import Tasker
    except Exception as exc:  # pragma: no cover
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
    shot = Path(log_dir or ".") / "diagnose_navigate_probe.png"
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
                out["nodes"][node] = {"hit": None, "note": "未产生节点详情"}
                continue
            rd = tasker.get_node_detail(int(ids[0])).recognition
            out["nodes"][node] = {"hit": bool(getattr(rd, "hit", False)), "box": getattr(rd, "box", None)}
        except Exception as exc:
            out["nodes"][node] = {"error": str(exc)}
    return out


def build_findings(windows, binary, constants, navmesh, zones, route, logs, stale):
    findings = []
    failed = [w for w in windows if w["result"] == "Failed"]
    if failed:
        worst = max(failed, key=lambda w: w["duration_s"] or 0)
        findings.append(
            {
                "id": "N-ACTION-FAILED",
                "severity": "warn",
                "evidence_class": "log",
                "title": "%s 失败 %d 次，最长一次 %ss（%s → %s）" % (
                    worst["node"], len(failed), worst["duration_s"], worst["prev_ts"], worst["end_ts"]),
                "evidence": "窗口内 MapNavigator 子任务: %s；静默 %s；anchor 空转 %d 次" % (
                    _join_or_none(worst["navigator_subtasks"]),
                    worst["silent_gaps"][:3] or "无（低于阈值）",
                    worst.get("nextlist_failed_retries") or 0),
            }
        )
        retries = max((w.get("nextlist_failed_retries") or 0) for w in windows)
        if retries >= 5:
            findings.append(
                {
                    "id": "N-ANCHOR-RETRY-BURN",
                    "severity": "warn",
                    "evidence_class": "log",
                    "title": "失败后 anchor 重试空转 %d 次（1s/次），最后以 20s reco_timeout 收尾" % retries,
                    "evidence": "GotoTriggerPointMaybeTeleport_* 的 max_hit 用尽后 NextList.Failed 立即返回；"
                    "外层只看到 'Task timeout'，归因到错误节点",
                }
            )
    if binary.get("available") and not binary.get("matches"):
        findings.append(
            {
                "id": "N-BINARY-MD5",
                "severity": "blocking",
                "evidence_class": "static",
                "title": "部署的 cpp-algo 不是 1.0856 版（转向系数可能 2 倍超调）",
                "evidence": "md5=%s，期望 %s（web/linux/homesrv/auto_update.sh 的 WANT_MD5）"
                % (binary.get("md5"), binary.get("expect")),
            }
        )
    if not binary.get("available"):
        findings.append(
            {
                "id": "N-BINARY-ABSENT",
                "severity": "warn",
                "evidence_class": "static",
                "title": "找不到 agent/cpp-algo，无法核对版本",
                "evidence": binary.get("path", ""),
            }
        )
    if constants.get("available") and constants.get("kTurn360UnitsPerWidth") not in (None, 1.0856):
        findings.append(
            {
                "id": "N-SOURCE-STEERING",
                "severity": "warn",
                "evidence_class": "static",
                "title": "源码转向系数不是 1.0856（3.86 units/度）",
                "evidence": "navi_config.h kTurn360UnitsPerWidth=%s" % constants.get("kTurn360UnitsPerWidth"),
            }
        )
    if navmesh is None:
        findings.append(
            {
                "id": "N-NAVMESH-ABSENT",
                "severity": "blocking",
                "evidence_class": "static",
                "title": "找不到 base.nav(.gz)，MapNavigateAction 无路网可用",
                "evidence": "已查找 %s" % ", ".join(NAV_ASSET_HINTS),
            }
        )
    else:
        missing = [z for z, ok in (zones.get("zones") or {}).items() if not ok]
        if missing:
            findings.append(
                {
                    "id": "N-NAVMESH-ZONE",
                    "severity": "blocking",
                    "evidence_class": "static",
                    "title": "navmesh 里找不到路线声明的 zone：%s" % ", ".join(missing),
                    "evidence": "%s 前 %s MB 扫描结果" % (navmesh, zones.get("scanned_mb")),
                }
            )
    if route.get("available") and route.get("missing_referenced_nodes"):
        findings.append(
            {
                "id": "N-ROUTE-REF",
                "severity": "blocking",
                "evidence_class": "static",
                "title": "路线引用的节点未加载：%s" % ", ".join(route["missing_referenced_nodes"]),
                "evidence": "路线 %s 的 interact_text/interact_scan 指向这些节点" % route.get("defined_in"),
            }
        )
    if not logs.get("available"):
        findings.append(
            {
                "id": "N-NO-CPP-LOG",
                "severity": "warn",
                "evidence_class": "static",
                "title": "cpp-algo 内部日志缺失：导航失败原因无法定位",
                "evidence": logs.get("reason", "") + "；essence.log 只含 maafw 行",
            }
        )
    if stale:
        findings.append(
            {
                "id": "N-STALE-LOG",
                "severity": "warn",
                "evidence_class": "log",
                "title": "日志早于当前代码部署，窗口结论只作历史参考",
                "evidence": "日志末条 %s / 代码 mtime %s" % (stale["log_last_ts"], stale["code_epoch"]),
            }
        )
    return findings


def _join_or_none(items):
    return "、".join(items) if items else "无"


def code_epoch(repo):
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="走位链只读诊断（日志窗口 + 静态前置条件）")
    ap.add_argument("--log", action="append", default=[], help="essence.log 路径，可重复")
    ap.add_argument("--root", default=os.environ.get("MAAEND_ROOT", "~/maaend"), help="部署/仓库根")
    ap.add_argument("--repo", default=None, help="源码树根（缺省同 --root）")
    ap.add_argument("--node", default="GotoTriggerPointMove_VFTheHub", help="走位节点名（默认枢纽区）")
    ap.add_argument("--node-prefix", default="GotoTriggerPoint", help="日志侧匹配前缀")
    ap.add_argument("--zone", default=DEFAULT_ZONE, help="navmesh 里要核对的 zone（可重复用逗号分隔）")
    ap.add_argument("--expect-md5", default=DEFAULT_EXPECT_MD5, help="期望的 cpp-algo md5")
    ap.add_argument("--max-gap", type=float, default=20.0, help="静默阈值（秒）")
    ap.add_argument("--max-scan-mb", type=float, default=64.0, help="navmesh 扫描上限（MB）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--json-out", default="", help="把 JSON 另存到该路径")
    ap.add_argument("--probe", action="store_true", help="追加一次只读截图识别评分")
    ap.add_argument("--sock", default=os.environ.get("MAAEND_SOCK", ""), help="WlRoots socket（probe 用）")
    ap.add_argument("--log-dir", default="", help="probe 时 tasker 日志/截图目录")
    args = ap.parse_args(argv)

    logs_paths = [Path(p).expanduser() for p in args.log]
    if not logs_paths:
        env_log = os.environ.get("MAAEND_ESSENCE_LOG")
        if env_log:
            logs_paths = [Path(env_log).expanduser()]
        else:
            for cand in ("~/maaend/essence.log", "~/maaend/nightly.log"):
                path = Path(cand).expanduser()
                if path.is_file():
                    logs_paths = [path]
                    break
    missing = [str(p) for p in logs_paths if not p.is_file()]
    logs_paths = [p for p in logs_paths if p.is_file()]
    if not logs_paths:
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
    warns = []
    for path in logs_paths:
        part = parse_log(path)
        events.extend(part["events"])
        warns.extend(part["warns"])

    windows = nav_windows(events, args.node_prefix, args.max_gap)
    epoch = code_epoch(repo)
    last_ts = events[-1]["ts"] if events else None
    stale = None
    if epoch and last_ts:
        try:
            if datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S.%f") < datetime.fromisoformat(epoch):
                stale = {"log_last_ts": last_ts, "code_epoch": epoch}
        except ValueError:
            stale = None

    binary = check_binary(root, args.expect_md5)
    constants = source_constants(repo)
    navmesh = find_navmesh(root)
    route = route_report(root, repo, args.node)
    zones = ",".join([args.zone, *(route.get("zones") or [])]) if route.get("zones") else args.zone
    zone_list = sorted({z.strip() for z in zones.split(",") if z.strip()})
    zone_scan = {"zones": dict.fromkeys(zone_list), "note": "navmesh 缺失"}
    if navmesh is not None:
        zone_scan = scan_zones(navmesh, zone_list, args.max_scan_mb)
    cpp_logs = cpp_algo_logs(root)

    probe = None
    if args.probe:
        dirs = [root / "resource", root / "assets" / "resource", root / "web" / "resource_web"]
        probe = probe_readonly(args.sock, dirs, PROBE_NODES, args.log_dir or str(Path.home() / "maaend-log"))

    findings = build_findings(windows, binary, constants, navmesh, zone_scan, route, cpp_logs, stale)
    blocking = [f for f in findings if f["severity"] == "blocking"]
    warn = [f for f in findings if f["severity"] == "warn"]
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "diagnose_navigate.py",
        "inputs": {
            "logs": [str(p) for p in logs_paths],
            "root": str(root),
            "repo": str(repo),
            "node": args.node,
            "zones": zone_list,
            "expect_md5": args.expect_md5,
            "max_gap_s": args.max_gap,
        },
        "freshness": {"code_epoch": epoch, "log_last_ts": last_ts, "log_precedes_code": bool(stale)},
        "log": {
            "events": len(events),
            "windows": windows,
            "notable_warns": warns[:10],
            "warn_counts": {
                key: sum(1 for w in warns if key in w["line"])
                for key in ("target rect is empty", "Task timeout", "task not found",
                            "Wrong ocr_result size", "invalid node id")
            },
        },
        "static": {
            "binary": binary,
            "source_constants": constants,
            "navmesh_path": str(navmesh) if navmesh else None,
            "navmesh_zones": zone_scan,
            "route": route,
            "cpp_algo_logs": cpp_logs,
        },
        "probe": probe,
        "findings": findings,
        "verdict": {
            "static_blocking": [f["id"] for f in blocking if f["evidence_class"] == "static"],
            "warnings": [f["id"] for f in warn],
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
    print("== 走位链只读诊断 ==")
    print("日志     : %s" % ", ".join(report["inputs"]["logs"]))
    fresh = report["freshness"]
    print("新鲜度   : 代码 mtime=%s 日志末条=%s → %s" % (
        fresh["code_epoch"], fresh["log_last_ts"],
        "日志早于代码部署，仅作历史参考" if fresh["log_precedes_code"] else "同一代代码"))
    failed_n = sum(1 for w in report["log"]["windows"] if w["result"] == "Failed")
    print("窗口     : %d 个（失败 %d / 成功 %d）" % (
        len(report["log"]["windows"]), failed_n, len(report["log"]["windows"]) - failed_n))
    for win in report["log"]["windows"]:
        print("  %s %s 于 %s，用时 %s（上一事件 %s @ %s，窗口内 %d 事件）" % (
            win["node"], "失败" if win["result"] == "Failed" else "成功", win["end_ts"],
            "-" if win["duration_s"] is None else "%.1fs" % win["duration_s"],
            win["prev_node"], win["prev_ts"], win["events_in_window"]))
        print("    MapNavigator 子任务: %s" % _join_or_none(win["navigator_subtasks"]))
        for gap in win["silent_gaps"][:3]:
            print("    静默 %6.1fs  %s → %s" % (gap["gap_s"], gap["from"], gap["to"]))
        if win.get("nextlist_failed_retries"):
            print("    anchor 重试空转: %d 次" % win["nextlist_failed_retries"])
    static = report["static"]
    binary = static["binary"]
    if binary.get("available"):
        print("cpp-algo : md5=%s %s（期望 %s）%s" % (
            binary["md5"], "匹配" if binary["matches"] else "不匹配", binary["expect"],
            "mtime=" + binary["mtime"]))
    else:
        print("cpp-algo : %s" % binary.get("reason"))
    const = static["source_constants"]
    if const.get("available"):
        print("源码常数 : kTurn360UnitsPerWidth=%s kLocalizationLossTimeoutMs=%s kZoneConfirmTimeoutMs=%s"
              % (const["kTurn360UnitsPerWidth"], const["kLocalizationLossTimeoutMs"], const["kZoneConfirmTimeoutMs"]))
    print("navmesh  : %s" % (static["navmesh_path"] or "未找到"))
    if static["navmesh_zones"].get("zones"):
        print("  zone 命中: %s" % static["navmesh_zones"]["zones"])
    route = static["route"]
    if route.get("available"):
        print("路线     : %s 定义于 %s" % (report["inputs"]["node"], route["defined_in"]))
        print("  zones=%s navmesh_points=%d interacts=%s 缺失引用=%s" % (
            route["zones"], len(route["navmesh_points"]), route["interacts"],
            route["missing_referenced_nodes"] or "无"))
        print("  on_error=%s timeout=%s" % (route["on_error"], route["timeout"]))
    else:
        print("路线     : %s" % route.get("reason"))
    logs = static["cpp_algo_logs"]
    print("cpp 日志 : %s" % ("%s（%d 个文件）" % (logs["dir"], len(logs["files"])) if logs.get("available")
                            else logs.get("reason")))
    print("结论     :")
    for item in report["findings"]:
        print("  [%-8s][%-10s] %-22s %s" % (
            item["severity"], item["evidence_class"], item["id"], item["title"]))
        print("      依据: %s" % item["evidence"])
    if report["probe"]:
        print("只读评分 : %s" % json.dumps(report["probe"].get("nodes", report["probe"]),
                                          ensure_ascii=False)[:800])
    print("退出码   : %d" % report["verdict"]["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
