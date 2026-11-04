# web/linux —— 云·终末地网页端 Linux 运行层

在无桌面的 Linux（homesrv：Ubuntu 24.04 + sway headless + Chrome）上跑 MaaEnd 的云·终末地网页版。本目录只做「运行层」：任务编排、页面控制、资源覆盖，不改上游 `resource/pipeline` 的任务逻辑。

## 分层

```text
cli/            maaend_web/cli   —— 命令行入口，只做参数解析与编排
runtime/        maaend_web/*.py   —— 与 MaaFramework / CDP / 系统交互
core/           maaend_web/*.py   —— 纯逻辑，不 import maa，可离线单测
```

依赖方向单向：`cli → runtime → core`。`core` 里的预设解析、计划筛选、结果记录不依赖框架，换机器也能跑。

## 目录

| 路径 | 作用 |
| --- | --- |
| `maaend_web/config.py` | 路径、环境变量、任务超时、CDP 端口，单一真源 |
| `maaend_web/preset.py` | MXU 预设 → `pipeline_override`（选项树递归展开、占位符类型转换） |
| `maaend_web/plan.py` | `--tasks` / `--only` / `--from --to` 的任务选择 |
| `maaend_web/results.py` | 逐任务结果落 jsonl + 汇总 |
| `maaend_web/framework.py` | LD_PRELOAD 自愈、LinuxController、go-service + cpp-algo 生命周期 |
| `maaend_web/recovery.py` | 进世界判定、恢复节点链、硬重置、失败截图 |
| `maaend_web/page.py` | 页面状态机（九态求值 → 分支 → 动作），对应 MaaEnd#6746 的 `prepare_host` |
| `maaend_web/cdp.py` | CDP 会话、`CdpController`（云串流原生帧 + 输入注入） |
| `maaend_web/overlay.py` | 浮层策略：悬浮球 + 延迟角标，注入并自愈 |
| `page_js.py` | 页面侧 JS 源码（状态判定 + 输入策略），Python 与 node 测试共用 |
| `homesrv/` | 部署层：cron/夜间链/几何/自动更新/选项基线 |
| `tools/`（仅部署仓库） | 一次性诊断脚本，不随上游发布；见 `yuhuan-zhen/MaaEnd-web-linux` |
| `tests/` | Python unittest + node:test |

顶层的 `run_daily_linux.py`、`resolve_preset.py`、`page_state.py`、`cdp_controller.py`、`overlay_ctl.py` 是兼容 shim：生产 cron 与环境变量路径不变，实现已经移进 `maaend_web/`。

## 运行

```bash
# 只打印计划，不连控制器
python3 web/linux/run_daily_linux.py --instance hmuddz8 --dry-run

# 单任务（外层已有重试链时用 --attempts 1，避免叠加）
python3 web/linux/run_daily_linux.py --instance hmuddz8 --tasks WebStartGame --attempts 1

# 全量日常（homesrv 生产入口，含启动/收尾/日志轮转）
bash web/linux/homesrv/daily_run_homesrv.sh

# 基质独立链：最多 6 轮，成功 4 轮即停
bash web/linux/homesrv/essence_run_homesrv.sh
```

环境变量（都有默认值，生产由 `homesrv/lib.sh` 统一导出）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MAAEND_DIST` / `MAAEND_ROOT` | `~/maaend` | 发行版根目录（resource/interface/agent） |
| `MAAEND_WEB` | `<root>/web` | 本仓库部署位置 |
| `MAAEND_RES_DIRS` | 四层深合并 | `resource:resource_web:resource_web_linux:resource_web_homesrv` |
| `MAA_AGENT_BIN` | `<root>/agent/go-service` | go-service 路径 |
| `MAA_AGENT_LIB` | `<dir>/maafw` | agent 的 `LD_LIBRARY_PATH` |
| `MAA_LOG_DIR` | `~/maaend-log` | 框架日志目录，必须可写 |
| `MAAEND_WEB_CDP_PORT` | `9334` | Chrome DevTools 端口 |

## 测试

```bash
# Python：core 纯逻辑 + 页面状态机 + 浮层判定（不需要 maa）
python3 -m unittest discover -s web/linux/tests -v

# JS：页面状态判定 / 输入策略 / 覆盖层分层
node --test web/linux/tests/*.test.mjs
```

## 与上游的关系

- 基线：MaaEnd `v2.35.0-beta.1`，覆盖层只放「网页端与 PC 客户端不同」的节点。
- 上游 `feat/web-linux-layer` 分支是本目录的上游参考实现；本仓库定期用 `homesrv/auto_update.sh` 跟进发行版，但 **`auto_update.sh` 不碰 `web/`**。
- `auto_update.sh` 会用发行版覆盖 `tasks/`。仓库里对 `tasks/` 的修改（vn 服包名、选项树修正）在更新后需要重新叠加，见 `docs/refactor-20261104/PLAN.md` 的部署注意事项。

## 已知限制

- 云版地图没有「传送点列表 / 确认框」，传送链按「点锚点 → 点传送胶囊 → 等 LOADING」重写。
- cpp-algo 必须停在 1.0856 版（3.86 units/度）；发行版自带的新版按 7.93 units/度算，会让导航 2 倍超调、永不收敛。
- 指针累计到视口边缘后 `post_relative_move` 仍返回成功但画面不动；长时间任务前需要回中。
- Chrome 用 SwiftShader 软渲染，2560×1440 会让 gpu-process 跑到 599% CPU；720p 约 79%。
