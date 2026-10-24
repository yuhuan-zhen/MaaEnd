#!/usr/bin/env python3
"""T7 · 证据包汇总（把 T1-T6 的产物打成一份可交付的东西）

docs/08 §T7 要求：任何人拿一个目录 + commit sha 就能重跑。本脚本做三件事：

1. 采集六项环境（如果已存在 env.txt 就复用）
2. 扫描 evidence/ 下所有子目录，生成 index.md（每项测了什么、什么时候、关键数字）
3. 打成 zip，并打印需要脱敏提醒

用法：
  python3 t7_env_pack.py                       # 汇总 evidence/ 下所有产物
  python3 t7_env_pack.py --check-frames        # 额外列出可能含账号信息的帧
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import zipfile

import _common as c

SENSITIVE_HINTS = ("login", "account", "uid", "扫码", "手机号")


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def summarize_dir(directory: pathlib.Path) -> dict:
    info: dict = {"name": directory.name, "files": 0, "size_kb": 0, "summary": None}
    for item in directory.rglob("*"):
        if item.is_file():
            info["files"] += 1
            info["size_kb"] += item.stat().st_size // 1024
    summary_file = directory / "summary.json"
    if summary_file.exists():
        try:
            info["summary"] = json.loads(summary_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            info["summary"] = "summary.json 解析失败"
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="T7 证据包汇总")
    parser.add_argument("--root", default="evidence", help="证据根目录")
    parser.add_argument("--out", default="pr6696-evidence-pack.zip")
    parser.add_argument("--check-frames", action="store_true", help="列出可能含账号信息的文件")
    args = parser.parse_args()

    root = pathlib.Path(args.root)
    if not root.exists():
        raise SystemExit(f"{root} 不存在，先把 T1-T6 跑一遍")

    directories = sorted(d for d in root.iterdir() if d.is_dir())
    env = c.env_info()
    env_text = "\n".join(f"{k}: {v}" for k, v in env.items())

    lines = [
        "# pr6696 证据包索引",
        "",
        f"生成时间：{env['timestamp']}",
        "",
        "## 环境",
        "",
        "```text",
        env_text,
        "```",
        "",
        "## 各项产物",
        "",
        "| 目录 | 文件数 | 体积 | 关键结果 |",
        "| --- | --- | --- | --- |",
    ]
    index: dict = {"env": env, "items": []}
    for directory in directories:
        info = summarize_dir(directory)
        summary = info["summary"]
        brief = "—"
        if isinstance(summary, dict):
            keys = list(summary)[:3]
            brief = ", ".join(str(k) for k in keys)
        lines.append(f"| {directory.name} | {info['files']} | {info['size_kb']} KB | {brief} |")
        index["items"].append(info)

    frames = [p for p in root.rglob("*") if p.suffix.lower() in (".png", ".jpg")]
    lines += ["", f"## 帧文件（{len(frames)} 个）", ""]
    for frame in frames[:20]:
        lines.append(f"- {frame.relative_to(root)}  sha256:{sha256_of(frame)}")

    if args.check_frames:
        suspicious = [f for f in frames if any(h in f.name.lower() for h in SENSITIVE_HINTS)]
        lines += ["", "## 可能含账号信息", ""]
        lines += [f"- {f}" for f in suspicious] or ["- 未发现按文件名命中的可疑项（仍建议逐张看一遍 UI 角落）"]

    index_path = root / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(lines))

    with zipfile.ZipFile(args.out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root.parent))
    print(f"\n打包完成：{args.out}（{pathlib.Path(args.out).stat().st_size // 1024} KB）")
    print("提醒：截帧可能带账号 ID、昵称或任务进度，对外提供前按 maaend-test-image 的脱敏要求处理")
    shutil.rmtree(pathlib.Path("__pycache__"), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
