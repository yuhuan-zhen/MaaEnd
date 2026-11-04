"""把 MXU 预设实例（``config/mxu-MaaEnd.json``）解析成「任务 -> entry + pipeline_override」。

MXU 在 GUI 里做的事就是：读任务的 optionValues -> 按 option.cases 的 pipeline_override
合并成一个覆盖字典 -> 提交任务时传给框架。Linux 上没有 GUI，只能自己复现。

支持四种选项类型：
  switch   : {"type":"switch","value":bool}      -> case "Yes"/"No"
  checkbox : {"type":"checkbox","caseNames":[]}  -> 多个 case 依次合并
  select   : {"type":"select","caseName":str}    -> 单个 case
  input    : {"type":"input","values":{name:v}}  -> option 根上的 pipeline_override，{InputName} 占位

三条硬约束（每条都对应过一次线上故障）：

1. **选项树必须递归到底**。上游把 AutoStockStaple 的购买清单下沉到第三层（``*Items``），
   只展开两层会静默丢掉 28 条 attach，任务照常返回成功但一件不买。
2. **input / hotkey 型的 pipeline_override 在 option 根上**，不能只看 case：
   库存阈值/价格/最大次数都在这里，漏了就全用默认值。
3. **整串占位符要按 pipeline_type 转类型**。写成字符串 ``"4600"`` 会让 go-service 的
   int 字段反序列化失败并 return false，把原本正常的任务跑挂。

占位符替换规则（上游 interface.schema.json 的 inputItem.pipeline_type）：
  * 整串占位符（值就是 "{Name}"）——按 pipeline_type 转成 int/bool，保持 JSON 类型；
  * 嵌入字符串（"{Name}>{Other}"）——只替换文本，保持字符串。
取值顺序：optionValues.values[name] -> inputs[].default -> 缺失则整条 po 不合并
（宁可让静态 pipeline 的默认值生效，也不要写入一个解析不了的占位符）。

用法::

    inst, plan = load_preset("my-instance")          # 不给 --instance 时取预设里的第一个
    for item in plan:
        print(item.name, item.entry, item.n_override)

模块级 ``ROOT`` / ``CONFIG`` 只是兼容旧调用点（``homesrv/option_audit.py`` 读
``rp.ROOT`` / ``rp.CONFIG``）的默认值，取自 ``config.load_settings()``；
新代码请显式传 ``root`` / ``config_path``。
"""

import glob
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_settings
from .jsonc import load_jsonc

# 旧脚本里 ROOT/CONFIG 是模块级常量，option_audit.py 等外部调用点仍在读它们。
ROOT: Path = load_settings().root
CONFIG: Path = ROOT / "config" / "mxu-MaaEnd.json"

MAX_DEPTH = 12
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")

# 网页端自研任务：某些机器上 interface.json 没导入 tasks/web/WebTasks.json，
# 这里给一个等价映射兜底（entry 与接口里的一致）。
FALLBACK_ENTRY = {
    "WebStartGame": "WebStartGameEntry",
    "WebOpenMenu": "WebPressEsc",
    "WebCaptureProbe": "WebCaptureProbe",
}

# PlanItem 支持的键：字段本身 + 只读的 n_override，供 dict 风格访问。
_ITEM_KEYS = frozenset({"name", "entry", "enabled", "override", "notes", "error", "n_override"})

__all__ = [
    "CONFIG",
    "FALLBACK_ENTRY",
    "MAX_DEPTH",
    "ROOT",
    "PlanItem",
    "_render_value",
    "_typed",
    "case_names_of",
    "deep_merge",
    "load_all",
    "load_interface",
    "load_preset",
    "render",
    "resolve_task",
]


@dataclass
class PlanItem:
    """计划里的一项：任务名、入口、是否启用、展开后的覆盖与解析说明。

    除了 dataclass 属性，还支持 ``p["name"]`` / ``p.get("override")`` 这类 dict 风格访问，
    因为 homesrv 下的老脚本（``option_audit.py``）是这样读的。
    """

    name: str
    entry: str | None
    enabled: bool = True
    override: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def n_override(self) -> int:
        """顶层覆盖键的条数（与重构前日志里的「覆盖 N 项」一致）。"""
        return len(self.override)

    def __getitem__(self, key: str) -> Any:
        if key not in _ITEM_KEYS:
            raise KeyError(key)
        return self.n_override if key == "n_override" else getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """dict 风格的带默认值读取；未知键返回 ``default``。"""
        if key not in _ITEM_KEYS:
            return default
        return self[key]


def deep_merge(dst: dict, src: dict) -> dict:
    """dict 递归合并；其余（含列表）整体替换——与 pipeline_override 的语义一致。"""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def load_interface(root: Path | None = None) -> tuple[dict[str, dict], dict[str, dict]]:
    """读 ``<root>/interface.json`` 与它 import 的所有文件，返回 (任务表, 选项表)。

    ``root`` 传 None 时用模块级 ``ROOT``；解析失败的单文件跳过，不拖垮整轮。
    """
    base = Path(root) if root is not None else ROOT
    iface = load_jsonc(base / "interface.json")
    tasks: dict[str, dict] = {}
    options: dict[str, dict] = {}
    for pat in iface.get("import") or []:
        target = str(pat).replace("\\", "/")
        if not Path(target).is_absolute():
            target = str(base / target)
        for f in glob.glob(target):
            try:
                d = load_jsonc(f)
            except Exception:
                continue
            for k in ("task", "tasks"):
                for t in d.get(k) or []:
                    if isinstance(t, dict) and t.get("name"):
                        tasks[t["name"]] = t
            if isinstance(d.get("option"), dict):
                options.update(d["option"])
    return tasks, options


# 旧名：resolve_preset.py 的 shim 与 hs_list_tasks.py 都在调用不带参数的 load_all()。
load_all = load_interface


def _typed(raw, ptype):
    """按 inputItem.pipeline_type 转换整串占位符的值。"""
    s = str(raw).strip()
    if ptype == "int":
        try:
            return int(s)
        except ValueError:
            return str(raw)
    if ptype == "bool":
        return s.lower() in ("1", "true", "yes", "on")
    if ptype == "float":
        try:
            return float(s)
        except ValueError:
            return str(raw)
    return str(raw)


def render(node, mapping) -> Any:
    """结构化替换：不经过 JSON 文本往返，因此值里的引号/反斜杠不会破坏结构。"""
    if isinstance(node, dict):
        return {k: render(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [render(v, mapping) for v in node]
    if isinstance(node, str):
        m = _PLACEHOLDER.fullmatch(node)
        if m:
            name = m.group(1)
            if name in mapping:
                return _typed(*mapping[name])
            return node  # 未解析的占位符原样保留（调用方决定是否跳过）
        out = node
        for name, (raw, _pt) in mapping.items():
            out = out.replace(f"{{{name}}}", str(raw))
        return out
    return node


def _render_value(node, raw) -> Any:
    """把旧式 $value 占位符替换成给定字符串（保持字符串类型）。"""
    if isinstance(node, dict):
        return {k: _render_value(v, raw) for k, v in node.items()}
    if isinstance(node, list):
        return [_render_value(v, raw) for v in node]
    if isinstance(node, str):
        if node == "$value":
            return raw
        return node.replace("$value", raw)
    return node


def case_names_of(opt_key, value, options):
    """某个选项当前选中的 case 名列表。缺失时回落 option.default_case（与 MXU 一致）。"""
    o = options.get(opt_key) or {}
    cases = o.get("cases") or []
    names = [c.get("name") for c in cases]
    v = value or {}
    t = v.get("type") or o.get("type")
    default = o.get("default_case")

    if t == "switch":
        if "value" not in v or v.get("value") is None:
            if default in names:
                return [default]
            return ["Yes"] if "Yes" in names else (names[:1] if names else [])
        return ["Yes" if v.get("value") else "No"]
    if t == "checkbox":
        picked = v.get("caseNames")
        if picked is None:
            picked = default if isinstance(default, list) else ([default] if default else [])
        return [n for n in picked if n in names]
    if t == "select":
        one = v.get("caseName") or default
        return [one] if one in names else []  # 未知 case 不再静默回落第一个
    if t in ("input", "hotkey"):
        return [default] if default in names else (names[:1] if names else [])
    # 未知类型：取默认
    if isinstance(default, str):
        return [default]
    if isinstance(default, list):
        return [n for n in default if n in names]
    return []


def resolve_task(task: dict, options: dict, values: dict) -> tuple[dict, list[str]]:
    """把一个任务的 optionValues 展开成 pipeline_override，返回 (覆盖字典, 说明列表)。

    纯函数：不读文件、不打印、不抛 SystemExit；三条问题通道都写进 notes——``MISSING_INPUT``（声明了但取不到值，整条 po 不合并）、``UNKNOWN_CASE``（选了不存在的 case）、``TRUNCATED``（选项树超过 MAX_DEPTH）。
    """
    out: dict[str, Any] = {}
    notes: list[str] = []
    seen: set[str] = set()

    # 任务级 pipeline_override（schema 的 taskItem.pipeline_override）先落地，
    # 再由选项覆盖——选项是用户在 GUI 里的选择，优先级更高。
    if isinstance(task.get("pipeline_override"), dict):
        deep_merge(out, task["pipeline_override"])

    def walk_option(opt_key, depth):
        """递归展开一个选项：合并选中 case 的 pipeline_override，并继续下钻它的子选项。"""
        if opt_key in seen:
            return
        if depth > MAX_DEPTH:
            notes.append(f"TRUNCATED:{opt_key}")
            return
        seen.add(opt_key)
        o = options.get(opt_key) or {}
        val = values.get(opt_key) or {}
        otype = o.get("type")

        # input / hotkey：pipeline_override 在 option 根上，用 {InputName} 占位
        if otype in ("input", "hotkey") and isinstance(o.get("pipeline_override"), dict):
            po = o["pipeline_override"]
            mapping, missing = {}, []
            for inp in o.get("inputs") or []:
                nm = inp.get("name")
                raw = (val.get("values") or {}).get(nm)
                if raw is None or raw == "":
                    raw = inp.get("default")
                if raw is None:
                    missing.append(nm)
                    continue
                mapping[nm] = (str(raw), inp.get("pipeline_type") or "string")
            refs = set(_PLACEHOLDER.findall(json.dumps(po, ensure_ascii=False)))
            declared = [inp.get("name") for inp in (o.get("inputs") or []) if inp.get("name")]
            # 只有「声明为 input 但取不到值」才算缺失；其余 {X} 是运行时变量
            # （例如 {AutoStockCurrentStockBill}），必须原样保留。
            unresolved = sorted(n for n in refs if n in declared and n not in mapping)
            if unresolved:
                # 不合并：让静态 pipeline 的默认值生效，绝不写入字面量占位符
                notes.append(f"MISSING_INPUT:{opt_key}.{','.join(unresolved)}")
                return
            merged: Any = render(po, mapping)
            v = val.get("value")
            if v not in (None, ""):
                merged = _render_value(merged, str(v))
            deep_merge(out, merged)
            pairs = ",".join(f"{k}={v[0]}" for k, v in mapping.items())
            notes.append(f"{opt_key}={pairs or 'input'}")
            return

        chosen = case_names_of(opt_key, val, options)
        notes.append(f"{opt_key}={','.join(chosen) or '?'}")
        if otype == "checkbox":
            picked = val.get("caseNames")
            if picked is None:
                d = o.get("default_case")
                picked = d if isinstance(d, list) else ([d] if d else [])
            unknown = [n for n in picked if n not in [c.get("name") for c in (o.get("cases") or [])]]
            if unknown:
                notes.append(f"UNKNOWN_CASE:{opt_key}.{','.join(unknown)}")
        if otype == "select" and not chosen:
            notes.append(f"UNKNOWN_CASE:{opt_key}={val.get('caseName')}")
        for cname in chosen:
            case = next((c for c in (o.get("cases") or []) if c.get("name") == cname), None)
            if not case:
                continue
            po = case.get("pipeline_override")
            if isinstance(po, dict):
                v = val.get("value")
                deep_merge(out, _render_value(po, str(v)) if v not in (None, "") else po)
            for sub in case.get("option") or []:
                walk_option(sub, depth + 1)

    for opt_key in task.get("option") or []:
        walk_option(opt_key, 0)
    return out, notes


def _default_root(config_path: Path | None) -> Path:
    """``config_path`` 落在 ``<root>/config/`` 下时用它反推 root，否则用模块级 ``ROOT``。"""
    if config_path is not None:
        parent = Path(config_path).parent
        if parent.name == "config":
            return parent.parent
    return ROOT


def load_preset(
    instance: str,
    *,
    root: Path | None = None,
    config_path: Path | None = None,
) -> tuple[dict, list[PlanItem]]:
    """读预设实例并解析成计划，返回 (实例字典, 计划项列表)。

    ``instance`` 传空串时取配置文件里的第一个实例（CLI 不写 ``--instance`` 的默认行为）；
    找不到实例时抛 ``LookupError``（由 CLI 转成人话）；单个任务解析失败只落到该项的 ``notes``。
    """
    cfg_path = Path(config_path) if config_path is not None else None
    base = Path(root) if root is not None else _default_root(cfg_path)
    if cfg_path is None:
        cfg_path = base / "config" / "mxu-MaaEnd.json"

    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    inst = None
    instances = cfg.get("instances") or []
    if not instance and instances:
        instance = instances[0].get("id") or instances[0].get("name") or ""
    for i in instances:
        if i.get("id") == instance or i.get("name") == instance:
            inst = i
            break
    if not inst:
        raise LookupError(f"找不到实例: {instance}")

    tasks, options = load_interface(base)
    plan: list[PlanItem] = []
    for t in inst.get("tasks") or []:
        name = t.get("taskName")
        meta = tasks.get(name)
        if not meta:
            fb = FALLBACK_ENTRY.get(name)
            if fb:
                plan.append(
                    PlanItem(
                        name=name,
                        entry=fb,
                        enabled=t.get("enabled", True),
                        notes=["内置回退"],
                    )
                )
            else:
                plan.append(PlanItem(name=name, entry=None, error="任务不存在于接口"))
            continue
        try:
            ov, notes = resolve_task(meta, options, t.get("optionValues") or {})
        except Exception as e:  # 单个任务解析失败不拖垮整个计划
            plan.append(
                PlanItem(
                    name=name,
                    entry=meta.get("entry"),
                    enabled=t.get("enabled", True),
                    notes=[f"ERROR:{e}"],
                )
            )
            continue
        plan.append(
            PlanItem(
                name=name,
                entry=meta.get("entry"),
                enabled=t.get("enabled", True),
                override=ov,
                notes=notes,
            )
        )
    return inst, plan
