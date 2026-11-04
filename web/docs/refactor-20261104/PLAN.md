# 云·终末地 Linux 运行层重构方案（2026-11-04）

本文是本次重构的唯一契约。所有子任务共用这里的目录结构、模块边界与 API 签名；改动与本文冲突时，先改本文再改代码。

## 1. 背景与基线

仓库：`yuhuan-zhen/MaaEnd` 的 `feat/web-linux-refactor-20261104` 分支（与上游同构，运行层在 `web/linux/`）。

- homesrv 生产分支：`master` @ `4e98104`（14 个提交未推 origin，2026-11-04 仍在跑夜间链）。
- 上游参考分支：`D:\maaend-upstream` 的 `feat/web-linux-layer` @ `470d64432`。该分支已把 `web/linux` 重构过一轮，带 `page_state.py`、`cdp_controller.py`、`split_overlay.py`、`tests/`、`wsl/`。
- 两条线在 `d365e54` 分叉：生产线补部署与浮层，PR 线补状态机与测试。本次把两条线合成一条可维护的主干。

合并结果在本仓库分支 `feat/web-linux-refactor-20261104`，merge 提交 `3413c95`。

## 2. 实测问题清单

| # | 问题 | 证据 |
| --- | --- | --- |
| 1 | 68 个文件平铺在 `web/linux/`，生产入口、库、一次性探针混在一起 | `find web/linux -type f`，8041 行 |
| 2 | 硬编码路径（`/mnt/d/jiaoben/...`、`/root/maaagent/go-service`）散布在 6 个文件 | `grep -rn "mnt/d\|/root/maaagent" web/linux` |
| 3 | 无包结构，靠 `sys.path.insert` + 同目录 import | `run_daily_linux.py:19`、`resolve_preset.py:34` |
| 4 | `daily_run_homesrv.sh` 与 `essence_run_homesrv.sh` 约 60% 重复（会话变量/日志轮转/cleanup/启动/收尾） | 两文件 91 行 vs 116 行，逐段对比 |
| 5 | 无 Python 单测、无 `.gitattributes`，行尾 CRLF/LF 混杂导致 merge 假冲突 | 本次 merge 12 个冲突中 10 个是行尾差异 |
| 6 | 20+ 个 `hs_*.py` 一次性探针与生产代码同目录，无「非生产」标记 | `ls web/linux/hs_*.py` |
| 7 | 生产入口 `run_daily_linux.py` 的 `main()` 260 行，嵌套 5 个闭包，无法单测 | 文件 479 行 |

## 3. 目标结构

依赖方向单向：`cli → runtime → core`。`core` 不 import `maa`，可在无框架机器上单测。

```text
web/linux/
├── maaend_web/                 # 新增：可复用核心库
│   ├── __init__.py
│   ├── config.py               # 路径/环境变量/超时/端口，单一真源
│   ├── jsonc.py                # JSONC 读取
│   ├── preset.py               # MXU 预设 -> pipeline_override
│   ├── plan.py                 # --tasks/--only/--from-to 选择
│   ├── results.py              # jsonl 落盘 + 汇总
│   ├── framework.py            # LD_PRELOAD/控制器/agent 生命周期
│   ├── recovery.py             # in_world/recover/hard_reset/failshot
│   ├── page.py                 # 页面状态机（移植 page_state.py）
│   ├── cdp.py                  # CDP 会话与控制器（移植 cdp_controller.py）
│   ├── overlay.py              # 浮层策略（移植 overlay_ctl.py）
│   └── cli/
│       ├── __init__.py
│       ├── daily.py            # 日常编排
│       ├── probe.py            # 离线节点评分
│       ├── calibrate.py        # 转向标定
│       └── overlay.py          # 浮层 CLI（check/once/watch）
├── page_js.py                  # 保留顶层：JS 源码字符串，Python 与 node 测试共用
├── run_daily_linux.py          # 兼容 shim，生产 cron 路径不变
├── resolve_preset.py           # 兼容 shim
├── introspect_tasks.py         # 兼容 shim
├── page_state.py               # 兼容 shim
├── cdp_controller.py           # 兼容 shim
├── overlay_ctl.py              # 兼容 shim
├── calibrate_turn.py           # 兼容 shim
├── reset_page.py               # 薄 CLI（用 maaend_web.cdp）
├── leave_game.py               # 薄 CLI
├── enter_game.py               # 薄 CLI
├── linux_probe.py              # 薄 CLI（用 maaend_web.cli.probe）
├── homesrv/
│   ├── lib.sh                  # 新增：会话变量/日志轮转/启动/收尾
│   ├── daily_run_homesrv.sh    # 改为 source lib.sh + 差异
│   ├── essence_run_homesrv.sh  # 同上
│   ├── nightly_run_homesrv.sh  # 同上
│   └── ...                     # 其余脚本保持
├── tools/                      # 新增：一次性探针归档，README 标注非生产
│   └── README.md
└── tests/
    ├── test_config.py
    ├── test_preset.py
    ├── test_plan.py
    ├── test_page_state.py      # 从上游移植
    └── test_overlay_ctl.py     # 从上游移植
```

## 4. 模块 API 契约

以下是跨模块调用的最小签名。实现可以加私有辅助函数，但不得改这些名字与参数顺序。

```python
# maaend_web/config.py
@dataclass(frozen=True)
class Settings:
    root: Path
    web: Path
    resource_dirs: tuple[Path, ...]
    log_dir: Path
    probe_out: Path
    cdp_port: int
    wlr_socket: str
    agent_bin: Path
    agent_lib: Path

def load_settings(env: Mapping[str, str] | None = None) -> Settings: ...
TASK_TIMEOUTS: dict[str, int]
DEFAULT_TIMEOUT: int = 1200

# maaend_web/jsonc.py
def loads_jsonc(text: str) -> Any: ...
def load_jsonc(path: str | Path) -> Any: ...

# maaend_web/preset.py
@dataclass
class PlanItem:
    name: str
    entry: str | None
    enabled: bool = True
    override: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    @property
    def n_override(self) -> int: ...

def deep_merge(dst: dict, src: dict) -> dict: ...
def load_interface(root: Path) -> tuple[dict[str, dict], dict[str, dict]]: ...
def resolve_task(task: dict, options: dict, values: dict) -> tuple[dict, list[str]]: ...
def load_preset(instance: str, *, root: Path | None = None,
                config_path: Path | None = None) -> tuple[dict, list[PlanItem]]: ...

# maaend_web/plan.py
def select_plan(plan: Sequence[PlanItem], *, tasks: str = "", only: str = "",
                frm: int = 1, to: int = 99) -> list[PlanItem]: ...

# maaend_web/results.py
@dataclass
class TaskResult:
    name: str; entry: str; done: bool; succeeded: bool
    seconds: float; last_node: str | None; timeout: bool; attempt: int

class ResultWriter:
    def __init__(self, path: Path) -> None: ...
    def write(self, result: TaskResult) -> None: ...
    def summary(self, results: Sequence[TaskResult]) -> str: ...

# maaend_web/framework.py
def ensure_preload(log: Callable[[str], None] = print) -> None: ...
def find_wlr_socket(env: Mapping[str, str] | None = None) -> str: ...
def make_controller(kind: str, settings: Settings,
                    log: Callable[[str], None] = print): ...   # kind: "wlroots" | "cdp"
def start_agent(res, settings: Settings, *, bin_path: Path | None = None,
                tag: str | None = None,
                log: Callable[[str], None] = print): ...
def start_agents(res, settings: Settings, *,
                 log: Callable[[str], None] = print) -> list: ...
def setup_tasker(tasker, settings: Settings, log=print) -> None: ...

# maaend_web/recovery.py
class Recoverer:
    def __init__(self, tasker, ctrl, settings: Settings, log=print) -> None: ...
    def run_node(self, node: str, cap: int = 90) -> bool: ...
    def in_world(self) -> bool: ...
    def needs_start(self) -> bool: ...
    def recover(self, tag: str = "") -> bool: ...
    def hard_reset(self, tag: str = "") -> bool: ...
    def save_failshot(self, tag: str) -> None: ...

# maaend_web/cli/daily.py
def main(argv: list[str] | None = None) -> int: ...
```

## 5. 兼容层规则

1. `web/linux/*.py` 旧入口**不删、不改调用方式**，内容替换为 shim：`sys.path` 指向本目录，`from maaend_web.x import *`，保留 `if __name__ == "__main__"`。
2. CLI 参数只增不减。`run_daily_linux.py` 必须继续接受 `--only/--tasks/--from/--to/--instance/--skip-in-game-check/--attempts/--no-agent/--dry-run`；`--attempts` 默认 2。
3. 环境变量名不变：`MAAEND_DIST/MAAEND_ROOT/MAAEND_WEB/MAAEND_RES_DIRS/MAA_AGENT_BIN/MAA_AGENT_LIB/MAA_LOG_DIR/MAA_SAVE_DRAW/MAAEND_WEB_CDP_PORT/WLR_SOCKET`。
4. `homesrv/*.sh` 的对外行为不变：日志路径、rc 语义、cleanup 后 `chrome=0 agent=0 sway=0`。
5. 不新增第三方依赖。只用标准库 + `maa`（运行期）+ 可选 `PIL`（failshot）。

## 6. 子任务与文件边界

每个子代理只能写自己名下的文件；跨边界改动先报回来。

| 组 | 负责文件 | 规范来源 | 上游参考 |
| --- | --- | --- | --- |
| A core | `maaend_web/{__init__,config,jsonc,preset,plan,results}.py`、`tests/test_{config,preset,plan}.py` | `D:\maaend-upstream\pyproject.toml`（ruff py314/120）、`docs/zh_cn/developers/components-guide.md` | `D:\maaend-upstream\web\linux\resolve_preset.py`、`introspect_tasks.py`、interface schema |
| B runtime | `maaend_web/{framework,recovery}.py`、`maaend_web/cli/{__init__,daily}.py`、`run_daily_linux.py` | MaaFramework Python 绑定、`docs/zh_cn/developers/custom.md` | `D:\maaend-upstream\web\linux\run_daily_linux.py`（状态机/控制器选择/failshot） |
| C page | `maaend_web/{page,cdp,overlay}.py`、`maaend_web/cli/overlay.py`、`tests/test_{page_state,overlay_ctl}.py` | CDP 协议、`D:\maaend-upstream\web\linux\tests\` | `D:\maaend-upstream\web\linux\{page_state,cdp_controller,overlay_ctl}.py` |
| D deploy | `homesrv/lib.sh`、`homesrv/{daily,essence,nightly}_run_homesrv.sh` | ShellCheck、cron/systemd 约定 | `D:\maaend-upstream\web\linux\homesrv\daily_run_homesrv.sh`（更短的版本） |
| E pipeline | `web/resource_web/pipeline/nodes.json`、`web/resource_web_homesrv/pipeline/nodes.json`、`tasks/*.json` | `.agents/skills/pipeline-guide/SKILL.md` + `field-reference.md`、`.prettierrc` | 上游 `assets/resource/pipeline/` 同节点写法 |

## 7. 验收

每组交付后由主代理统一跑：

```bash
uv run ruff check web/linux                       # 0 error
uv run python -m unittest discover -s web/linux/tests -v
python3 -m py_compile web/linux/maaend_web/**/*.py
bash -n web/linux/homesrv/*.sh
git diff --check                                  # 无行尾空白
```

行为验收在 homesrv 上做：`run_daily_linux.py --dry-run` 输出与重构前逐字一致；`run_daily_linux.py --tasks WebStartGame --attempts 1` 能进游戏。

## 8. 回滚

- 代码回滚：`git checkout master -- web/linux`（重构全部在新分支）。
- 生产回滚：homesrv 的 `~/maaend` 不受影响；部署时先 `cp -a web/linux web/linux.bak-$(date +%Y%m%d-%H%M)`。
