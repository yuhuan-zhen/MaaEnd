#!/usr/bin/env python3
"""把一轮补测的「文档 + 脚本 + 日志 + 证据」打成一个自带 manifest 的 zip。

为什么要打包：单看数字没有说服力，别人要能沿着包里的东西自己复现——
文档说明为什么这样测、脚本是原始代码、日志是全量输出、证据目录带 env/command。

用法（在 tools/pr6696-tests 下）：

    python3 pack_report.py --tag t5j --title "生产路径补测"
    python3 pack_report.py --tag t5j --evidence-prefix t5j-2026   # 指定证据目录前缀

默认收录：
    - 以 tag 开头的 Markdown（如 T5j-*.md）
    - 以 tag 开头的脚本（如 t5j_*.py）
    - arrow_ruler.py / _common.py（复现必需）
    - evidence/<prefix>* 目录下的全部文件
    - evidence/<tag>-*.log 与 *.json
输出：reports/<tag>-<title>-<日期>.zip，含 manifest.json（每个文件的 sha256）
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import zipfile

BASE = pathlib.Path(__file__).resolve().parent
ALWAYS = ("arrow_ruler.py", "_common.py")


def collect(tag: str, evidence_prefix: str) -> list[pathlib.Path]:
    items: set[pathlib.Path] = set()
    upper = tag.upper()

    for pattern in (f"{upper}-*.md", f"{tag}-*.md", f"{tag}_*.py"):
        items.update(p for p in BASE.glob(pattern) if p.is_file())
    for name in ALWAYS:
        path = BASE / name
        if path.exists():
            items.add(path)

    evidence = BASE / "evidence"
    if evidence.exists():
        for pattern in (f"{evidence_prefix}*", f"{tag}-*.log", f"{tag}-*.json"):
            for path in evidence.glob(pattern):
                if path.is_dir():
                    items.update(p for p in path.rglob("*") if p.is_file())
                elif path.is_file():
                    items.add(path)
    return sorted(items)


def main() -> int:
    parser = argparse.ArgumentParser(description="打包一轮补测的文档/脚本/日志/证据")
    parser.add_argument("--tag", required=True, help="如 t5j")
    parser.add_argument("--title", default="补测", help="标题，仅用于文件名")
    parser.add_argument("--evidence-prefix", default="", help="证据目录前缀，缺省同 tag")
    args = parser.parse_args()

    prefix = args.evidence_prefix or f"{args.tag}-2026"
    items = collect(args.tag, prefix)
    if not items:
        print("没有可打包的文件，检查 --tag / --evidence-prefix")
        return 1

    outdir = BASE / "reports"
    outdir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    out = outdir / f"{args.tag}-{args.title}-{stamp}.zip"

    manifest: dict[str, object] = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "tag": args.tag,
        "title": args.title,
        "files": [],
    }
    entries: list[dict[str, object]] = []
    for path in items:
        entries.append({
            "path": path.relative_to(BASE).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest["files"] = entries

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in items:
            archive.write(path, path.relative_to(BASE).as_posix())
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    print(f"{out}  ({out.stat().st_size} bytes, {len(items)} files)")
    for entry in entries:
        print(f"  {entry['path']}  {entry['bytes']} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
