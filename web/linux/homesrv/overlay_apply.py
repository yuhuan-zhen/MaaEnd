#!/usr/bin/env python3
"""把仓库侧的覆盖层叠回部署树（升级/部署后跑，幂等）。

背景
----
``auto_update.sh`` 用发行版整包替换 ``resource/``、``interface.json``、``tasks/``、``agent/``。
仓库里对任务的改动（``web/tasks/*.json`` 及其在 ``interface.json`` 的 import）和对发行版
pipeline 的定点修补都会被冲掉（遗留 5）。本脚本按同目录 ``overlay_ops.json`` 的声明，把这些
覆盖层重新压到部署树上；每晚跑一次，也可以由 ``deploy.sh`` 在部署后立刻跑。

三类操作
--------
* ``tasks``：``<src>/web/tasks/**/*.json`` → ``<root>/tasks/<相对路径>``
* ``interface_imports``：确保 ``interface.json`` 的 ``import`` 数组含这些条目（缺则追加）
* ``text_patches``：在目标文件的锚点窗口内做一次精确文本替换（保持 JSONC 原格式，不做 JSON 往返）

``deploy.sh`` 在仓库侧调用时多给一个 ``--stage-from <仓库根>``：先把清单 ``tasks.include``
点名的文件从 ``<仓库根>/<tasks.stage_from>`` 拷到部署树的 ``<tasks.source>``（默认 ``web/tasks``），
再执行上面的叠回。升级场景（``auto_update.sh``）没有仓库，直接用部署树里已暂存的副本。
``include`` 为空时才整目录暂存；点名列表是刻意的——发行版 tasks/ 比仓库新，整包覆盖等于降级。

用法
----
    python3 overlay_apply.py --root ~/maaend              # 叠回（幂等）
    python3 overlay_apply.py --root ~/maaend --dry-run    # 只报告会做什么
    python3 overlay_apply.py --root ~/maaend --check      # 只校验；未叠回则 rc=1

退出码
------
0  成功（``--check``：全部已叠回）
1  有操作失败，或 ``--check`` 发现未叠回
2  参数 / 清单 / 目录错误
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPS_FILE = HERE / "overlay_ops.json"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def log(msg):
    """统一前缀，方便在 upgrade.log 里 grep。"""
    print("[overlay] %s" % msg, flush=True)


def load_ops(path):
    """读清单并做最小校验；坏清单直接抛 ValueError（调用方转成 rc=2）。"""
    try:
        ops = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError("读不到清单 %s：%s" % (path, exc)) from exc
    except json.JSONDecodeError as exc:
        raise ValueError("清单不是合法 JSON %s：%s" % (path, exc)) from exc
    if not isinstance(ops, dict):
        raise ValueError("清单根节点必须是对象")
    for key in ("tasks", "interface_imports", "text_patches"):
        if key in ops and not isinstance(ops[key], list if key != "tasks" else dict):
            raise ValueError("清单字段 %s 类型不对" % key)
    return ops


def norm_import(entry):
    """import 条目比较时忽略前导 ``./``（MaaEnd 两种写法都出现过）。"""
    text = str(entry).strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def iter_task_files(src_root, subdir):
    """列出 ``<src_root>/<subdir>/**/*.json``，按相对路径排序保证输出稳定。"""
    base = Path(src_root) / subdir
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.json") if p.is_file())


def stage_tasks(root, stage_from, cfg, dry_run):
    """把仓库里点名要叠回的任务文件拷到部署树的 tasks 源目录（默认 web/tasks）。

    只在 ``deploy.sh``（仓库侧）调用；升级场景没有仓库，源就是部署树里已暂存的副本。
    返回 ``(copied, unchanged, failed)``。
    """
    source = cfg.get("source") or "web/tasks"
    stage_dir = cfg.get("stage_from") or ""
    include = cfg.get("include") or []
    if not stage_dir:
        return 0, 0, 0
    base = Path(stage_from) / stage_dir
    if not base.is_dir():
        log("stage：仓库里没有 %s（跳过）" % base)
        return 0, 0, 0
    if include:
        files = [base / rel for rel in include]
        missing = [str(p) for p in files if not p.is_file()]
        if missing:
            log("stage：清单点名的文件不存在：%s" % ", ".join(missing))
            return 0, 0, len(missing)
    else:
        files = sorted(p for p in base.rglob("*.json") if p.is_file())
    copied = unchanged = 0
    for src_file in files:
        rel = src_file.relative_to(base)
        dst_file = Path(root) / source / rel
        payload = src_file.read_bytes()
        if dst_file.is_file() and dst_file.read_bytes() == payload:
            unchanged += 1
            continue
        if dry_run:
            log("stage 将复制：%s -> %s" % (rel, dst_file))
            copied += 1
            continue
        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_bytes(payload)
        except OSError as exc:
            log("stage 复制失败 %s：%s" % (dst_file, exc))
            return copied, unchanged, 1
        log("stage 已复制：%s" % rel)
        copied += 1
    return copied, unchanged, 0


def read_text(path):
    """按 UTF-8 读文本并保留「原来有没有 BOM」这个信息。"""
    raw = Path(path).read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), has_bom


def write_text(path, text, bom=False):
    """原子写回：先写同目录临时文件再 replace，避免半截文件被下一次运行读到。"""
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    tmp = Path(str(path) + ".overlay-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def apply_tasks(root, src_root, subdir, target, dry_run, check, include=None):
    """把仓库 tasks 覆盖到部署树；返回 (copied, unchanged, failed)。

    ``include`` 非空时只处理点名的相对路径（清单里只列我们自己维护的任务文件）。
    """
    copied = unchanged = failed = 0
    files = iter_task_files(src_root, subdir)
    if include:
        base = Path(src_root) / subdir
        wanted = {str(x).replace("\\", "/") for x in include}
        files = [p for p in files if str(p.relative_to(base)).replace("\\", "/") in wanted]
    if not files:
        log("tasks：%s 下没有匹配的 json（跳过）" % (Path(src_root) / subdir))
        return 0, 0, 0
    for src_file in files:
        rel = src_file.relative_to(Path(src_root) / subdir)
        dst_file = Path(root) / target / rel
        payload = src_file.read_bytes()
        if dst_file.is_file() and dst_file.read_bytes() == payload:
            unchanged += 1
            continue
        if check:
            log("tasks 未叠回：%s" % dst_file)
            failed += 1
            continue
        if dry_run:
            log("tasks 将复制：%s -> %s" % (rel, dst_file))
            copied += 1
            continue
        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            dst_file.write_bytes(payload)
        except OSError as exc:
            log("tasks 复制失败 %s：%s" % (dst_file, exc))
            failed += 1
            continue
        log("tasks 已复制：%s" % rel)
        copied += 1
    return copied, unchanged, failed


def apply_imports(root, wanted, dry_run, check):
    """确保 interface.json 的 import 含清单里的条目；返回 (added, present, failed)。"""
    if not wanted:
        return 0, 0, 0
    iface = Path(root) / "interface.json"
    if not iface.is_file():
        log("interface.json 不存在：%s" % iface)
        return 0, 0, len(wanted)
    text, has_bom = read_text(iface)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log("interface.json 不是合法 JSON：%s" % exc)
        return 0, 0, len(wanted)
    imports = data.get("import")
    if not isinstance(imports, list):
        log("interface.json 的 import 不是数组，跳过（需要人工看）")
        return 0, 0, len(wanted)

    present = {norm_import(x) for x in imports}
    missing = [x for x in wanted if norm_import(x) not in present]
    added = 0
    failed = 0
    for entry in missing:
        # import 指向的文件必须真的在，否则 interface 加载会整包失败；
        # dry-run 时文件可能还没被 stage/tasks 叠回，按「将会产生」处理。
        rel = norm_import(entry)
        exists = (Path(root) / rel).is_file()
        if not exists and not dry_run:
            log("import 目标缺失，拒绝写入：%s" % rel)
            failed += 1
            continue
        if check:
            log("import 未叠回：%s" % entry)
            failed += 1
            continue
        if dry_run:
            log("import 将追加：%s%s" % (entry, "" if exists else "（目标文件由 tasks 叠回产生）"))
            added += 1
            continue
        imports.append(entry)
        present.add(norm_import(entry))
        log("import 已追加：%s" % entry)
        added += 1
    if added and not dry_run and not check:
        data["import"] = imports
        write_text(iface, json.dumps(data, ensure_ascii=False, indent=2) + "\n", bom=has_bom)
        log("interface.json 已写回（import %d 条）" % len(imports))
    return added, len(wanted) - len(missing), failed


def _ws_pattern(literal):
    """把一段 JSON 文本变成「空白不敏感」的正则：``": "`` 与 ``":"``、换行缩进都能命中。

    上游的 nodes.json 是 ``json.dump(indent=4)``（冒号后有空格），但任何一次重新序列化
    （紧凑输出、不同 indent）都会让字面量匹配失效；patch 失败会让整次升级回滚，所以这里
    按空白切片再逐段转义（``re.escape`` 会把空格转成 ``\\ ``，不能直接替换）。
    """
    parts = [re.escape(part) for part in re.split(r"\s+", literal.strip())]
    return r"\s*".join(parts)


def apply_text_patches(root, patches, dry_run, check):
    """在锚点窗口内做一次精确替换；返回 (applied, already, failed)。"""
    applied = already = failed = 0
    for patch in patches:
        rel = patch.get("file") or ""
        anchor = patch.get("anchor") or ""
        anchor_re = patch.get("anchor_regex") or ""
        find = patch.get("find") or ""
        replace = patch.get("replace") or ""
        window = int(patch.get("window") or 900)
        path = Path(root) / rel
        if not rel or not find or not replace:
            log("text_patches 条目缺 file/find/replace：%r" % patch)
            failed += 1
            continue
        if not path.is_file():
            log("text_patches 目标不存在：%s" % path)
            failed += 1
            continue
        text, has_bom = read_text(path)
        if anchor_re:
            match = re.search(anchor_re, text)
            start = match.start() if match else -1
        else:
            start = text.find(anchor) if anchor else 0
        if start < 0:
            log("text_patches 找不到锚点 %r（上游结构变了？）：%s" % (anchor_re or anchor, rel))
            failed += 1
            continue
        segment = text[start : start + window]
        find_re = re.compile(_ws_pattern(find))
        repl_re = re.compile(_ws_pattern(replace))
        match = find_re.search(segment)
        if match:
            if check:
                log("patch 未叠回：%s（%s）" % (rel, find))
                failed += 1
                continue
            if dry_run:
                log("patch 将应用：%s（%s -> %s）" % (rel, find, replace))
                applied += 1
                continue
            new_segment = segment[: match.start()] + replace + segment[match.end() :]
            write_text(path, text[:start] + new_segment + text[start + window :], bom=has_bom)
            log("patch 已应用：%s（%s -> %s）" % (rel, find, replace))
            applied += 1
        elif repl_re.search(segment):
            already += 1
        else:
            log("text_patches 窗口内既没有待替换串也没有目标串（需人工看）：%s" % rel)
            failed += 1
    return applied, already, failed


def main(argv=None):
    """命令行入口：按清单顺序叠回，最后打印一行可 grep 的汇总。"""
    ap = argparse.ArgumentParser(prog="overlay_apply.py", description="把仓库侧覆盖层叠回部署树（幂等）")
    ap.add_argument("--root", default=os.environ.get("MAAEND_DIST") or os.path.expanduser("~/maaend"),
                    help="部署目录，默认 $MAAEND_DIST 或 ~/maaend")
    ap.add_argument("--src", default="", help="仓库源码根（默认同 --root，即已部署的 web/tasks）")
    ap.add_argument("--ops", default=str(OPS_FILE), help="覆盖层清单，默认脚本同目录的 overlay_ops.json")
    ap.add_argument("--stage-from", default="", help="仓库根：先把 tasks.include 点名的文件暂存到部署树（deploy.sh 用）")
    ap.add_argument("--dry-run", action="store_true", help="只报告会做什么，不写文件")
    ap.add_argument("--check", action="store_true", help="只校验是否已叠回；未叠回 rc=1")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser()
    if not root.is_dir():
        log("部署目录不存在：%s" % root)
        return EXIT_USAGE
    src_root = Path(args.src).expanduser() if args.src else root

    try:
        ops = load_ops(args.ops)
    except ValueError as exc:
        log(str(exc))
        return EXIT_USAGE

    tasks_cfg = ops.get("tasks") or {}
    subdir = tasks_cfg.get("source") or "web/tasks"
    target = tasks_cfg.get("target") or "tasks"
    # dry-run + stage：暂存还没发生，直接按「仓库里的来源目录 -> 部署树 tasks」预演，
    # 否则会误报「web/tasks 下没有 json」。
    apply_src = src_root
    apply_subdir = subdir
    if args.dry_run and args.stage_from and tasks_cfg.get("stage_from"):
        apply_src = Path(args.stage_from).expanduser()
        apply_subdir = str(tasks_cfg["stage_from"])

    log(
        "root=%s src=%s ops=%s%s%s"
        % (root, src_root, args.ops, " [dry-run]" if args.dry_run else "", " [check]" if args.check else "")
    )
    staged = staged_unchanged = failed_stage = 0
    if args.stage_from:
        if args.check:
            log("--check 不写文件：跳过 stage，只校验部署树是否已叠回")
        else:
            staged, staged_unchanged, failed_stage = stage_tasks(
                root, Path(args.stage_from).expanduser(), tasks_cfg, args.dry_run
            )
    copied, unchanged, failed_tasks = apply_tasks(
        root, apply_src, apply_subdir, target, args.dry_run, args.check, tasks_cfg.get("include") or None
    )
    added, present, failed_imports = apply_imports(
        root, ops.get("interface_imports") or [], args.dry_run, args.check
    )
    patched, already, failed_patches = apply_text_patches(
        root, ops.get("text_patches") or [], args.dry_run, args.check
    )

    failed = failed_tasks + failed_imports + failed_patches + failed_stage
    log(
        "汇总：stage 新=%d 未变=%d；tasks 新=%d 未变=%d；import 新=%d 已有=%d；patch 应用=%d 已叠=%d；失败=%d"
        % (staged, staged_unchanged, copied, unchanged, added, present, patched, already, failed)
    )
    if failed:
        log("结果：未完成（%d 处失败/未叠回）" % failed)
        return EXIT_FAIL
    log("结果：已叠回（幂等，可重复跑）" if not args.check else "结果：全部已叠回")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
