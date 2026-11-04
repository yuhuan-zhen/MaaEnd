"""兼容层：JSONC 解析在 :mod:`maaend_web.jsonc`。

``python3 introspect_tasks.py [root]`` 仍可打印发行版里的任务/选项清单。
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.jsonc import load_jsonc

__all__ = ["load_jsonc", "main"]


def main(argv: list[str] | None = None) -> int:
    """打印 ``interface.json`` 导入的任务与选项默认值（调试用）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    root = args[0] if args else os.environ.get("MAAEND_ROOT", os.path.expanduser("~/maaend"))
    iface = load_jsonc(os.path.join(root, "interface.json"))

    files: list[str] = []
    for pat in iface.get("import") or []:
        p = pat.replace("\\", "/")
        if not os.path.isabs(p):
            p = os.path.join(root, p)
        files += sorted(glob.glob(p))

    tasks, options = [], {}
    for f in files:
        try:
            d = load_jsonc(f)
        except Exception as e:
            print(f"  ! {os.path.basename(f)} 解析失败: {e}")
            continue
        for k in ("task", "tasks"):
            if isinstance(d.get(k), list):
                tasks += [t for t in d[k] if isinstance(t, dict)]
        if isinstance(d.get("option"), dict):
            options.update(d["option"])

    print(f"任务数 {len(tasks)}   选项组 {len(options)}   （来源 {len(files)} 个文件）")
    print()
    print(f"{'#':<3} {'任务名':<24} {'entry':<34} 选项")
    for i, t in enumerate(tasks, 1):
        opts = ",".join(t.get("option") or []) or "-"
        print(f"{i:<3} {t.get('name')!s:<24} {t.get('entry')!s:<34} {opts}")

    print("\n=== 选项默认值 ===")
    for key, o in options.items():
        cases = o.get("cases") or []
        names = [c.get("name") for c in cases]
        dflt = o.get("default_case") or o.get("default")
        if dflt is None and cases:
            dflt = cases[0].get("name")
        print(f"  {key:<30} default={dflt!s:<16} cases={names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
