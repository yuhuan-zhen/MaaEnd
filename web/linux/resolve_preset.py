"""兼容层：实现已迁到 :mod:`maaend_web.preset`。

保留旧模块名与 ``ROOT`` / ``CONFIG`` / ``load_all`` / ``resolve_task`` 等导出，
供 ``homesrv/option_audit.py`` 与旧文档命令继续 import；新代码请直接
``from maaend_web.preset import ...``。

用法::

    python3 resolve_preset.py [实例 id] [--dump]    # 不写实例时用预设里的第一个

退出码：0 = 打印完成；1 = 找不到实例（``LookupError`` 转成 SystemExit 文案）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maaend_web.preset import *  # noqa: F403
from maaend_web.preset import __all__ as _core_all
from maaend_web.preset import load_preset

__all__ = list(_core_all)


def main(argv: list[str] | None = None) -> int:
    """``python3 resolve_preset.py <实例> [--dump]``：打印解析后的计划。"""
    args = list(sys.argv[1:] if argv is None else argv)
    iid = args[0] if args and not args[0].startswith("-") else ""
    dump = "--dump" in args
    try:
        inst, plan = load_preset(iid)
    except LookupError as e:
        raise SystemExit(str(e)) from None
    print(
        f"实例: {inst.get('name')} ({inst.get('id')})  "
        f"控制器={inst.get('controllerName')}  资源={inst.get('resourceName')}"
    )
    print(f"{'#':<3} {'任务':<22} {'entry':<32} {'覆盖项':<6} 状态")
    for i, p in enumerate(plan, 1):
        state = p.error or ("启用" if p.enabled else "禁用")
        print(f"{i:<3} {p.name:<22} {p.entry!s:<32} {p.n_override:<6} {state}")
    if dump:
        import json

        for p in plan:
            print(f"\n== {p.name}")
            print(json.dumps(p.override, ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
