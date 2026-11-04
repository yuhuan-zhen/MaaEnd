#!/usr/bin/env python3
"""打印发行版 ``interface.json`` 导入的任务与选项默认值（调试用）。

排查「预设里的任务名到底对应哪个 entry」「某个选项组的默认 case 是什么」时，
比逐个打开 JSON 快：它按 ``interface.json`` 的 ``import`` 数组把所有被导入文件读一遍
（JSONC，带注释也能读），再汇总成两张表。

用法::

    python3 web/linux/devtools/introspect_tasks.py                 # 默认读 ~/maaend
    python3 web/linux/devtools/introspect_tasks.py --root /opt/MaaEnd

退出码：0 = 打印完成；2 = 找不到/读不了 ``<root>/interface.json``。
"""

import argparse
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maaend_web.jsonc import load_jsonc


def main(argv: list[str] | None = None) -> int:
    """读 root 下的 interface.json，打印任务表与选项默认值。"""
    ap = argparse.ArgumentParser(description="打印发行版里的任务/选项清单")
    ap.add_argument(
        "--root",
        default=str(Path("~/maaend").expanduser()),
        help="发行版根目录（含 interface.json），默认 %(default)s",
    )
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser()

    iface_path = root / "interface.json"
    try:
        iface = load_jsonc(iface_path)
    except (OSError, ValueError) as e:
        print(f"[X] 读不到 {iface_path}: {e}")
        return 2

    files: list[str] = []
    for pat in iface.get("import") or []:
        p = str(pat).replace("\\", "/")
        if not Path(p).is_absolute():
            p = str(root / p)
        files += sorted(glob.glob(p))

    tasks, options = [], {}
    for f in files:
        try:
            d = load_jsonc(f)
        except Exception as e:
            print(f"  ! {Path(f).name} 解析失败: {e}")
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
