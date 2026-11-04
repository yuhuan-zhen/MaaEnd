# 云·终末地网页端运行层

在**无桌面的 Linux 服务器**上跑《云·终末地》网页版的日常：headless sway 提供合成器，Chrome 打开云端网页，MaaFramework 的 **Linux-Wlroots 控制单元**负责截图与虚拟键鼠，任务逻辑复用上游 `assets/` 的 pipeline 与资源。

本目录只做「运行层」：任务编排、页面状态、资源薄覆盖、部署脚本。不改上游 `assets/resource/pipeline` 的任务逻辑，也不把网页端的差异做成第二套 pipeline。

## 架构

```text
cron / 手动
  └─ homesrv/*.sh                     启动 → 跑 → 收尾（trap 保证失败也清理）
       ├─ headless sway (1280x720)    ← wlr-screencopy 取帧
       ├─ Chrome --ozone-platform=wayland → endfield.hypergryph.com/cloud
       └─ run_daily_linux.py
            ├─ maaend_web.cli         参数解析、任务选择、结果汇总
            ├─ maaend_web.*           控制器与 agent 生命周期、恢复、页面状态、浮层
            └─ MaaFramework           Linux-Wlroots 控制单元 + go-service + cpp-algo
```

依赖方向单向：`cli → runtime → core`。`core` 模块不 import `maa`，所以 `--help`、`--dry-run` 和全部单测都不需要装框架。

## 目录

| 路径 | 作用 |
| --- | --- |
| `linux/maaend_web/` | 运行层包：`cli`（入口）、runtime（控制器、框架、恢复、页面）、core（配置、预设、计划、结果、JSONC） |
| `linux/*.py` | 兼容 shim 与薄 CLI。生产 cron 与 `homesrv/*.sh` 调的就是这些固定路径 |
| `linux/devtools/` | 非生产工具：CDP 原生帧控制器、WSL 调试脚本。生产走 C++ `Linux-Wlroots` |
| `linux/homesrv/` | 部署层：起停、一键部署、夜间链、自动更新、选项审计 |
| `linux/tests/` | unittest + node:test，全部离线可跑 |
| `tools/` | 一次性 CDP 探针（抓帧、开会话、探 target），不进发行版 |
| `docs/` | 架构、部署、排障、诊断。索引见 [`docs/README.md`](./docs/README.md) |
| `pyproject.toml` | 本目录的 ruff 配置：`extend` 根配置，只追加两条豁免 |

网页端的任务定义跟上游一样放 `assets/tasks/`（`WebStartGame.json`），并在 `assets/interface.json` 的 `import` 里注册；运行层只读任务名，不认文件位置。

资源侧只有一层薄覆盖 `assets/resource_cloud_web/`（本轮从 `web/resource_web` 迁入），和上游 `resource_cloud` 一样由 `assets/interface.json` 的 `attach_resource_path` 挂到 `Linux-Wlroots` 控制器，不再靠 `MAAEND_RES_DIRS` 手工拼四层。

## 安装

前置：Linux（Ubuntu 24.04 实测）、MaaFramework 发行版（含 `resource/`、`interface.json`、`agent/`、`maafw/`）、Chrome、headless sway、Python ≥ 3.12（CI 用 3.14，与上游 `requires-python` 一致）。

部署形态是「发行版 + 本仓库叠加」：发行版解到 `~/maaend`，本仓库的 `web/` 放在 `~/maaend/web`，运行时只读 `~/maaend` 下的资源与 agent。完整步骤、备份与回滚见 [`docs/deployment.md`](./docs/deployment.md)。

只做静态检查与单测时不需要游戏环境，装开发依赖即可：

```bash
pnpm install    # markdownlint / prettier（仓库根的 devDependencies）
uv sync         # ruff（根 pyproject.toml 的 dev 组）
```

## 跑法

```bash
# 计划预览：只读 MXU 预设，不连控制器（预设默认取 $MAAEND_ROOT/config/mxu-MaaEnd.json）
MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --dry-run

# 单任务；外层已有重试链时用 --attempts 1，避免叠加
MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --tasks WebStartGame --attempts 1

# 一键日常：起浏览器 → 按预设跑 → 收尾
bash web/linux/homesrv/daily_run_homesrv.sh

# 基质独立链：最多 6 轮，成功 4 轮即停
bash web/linux/homesrv/essence_run_homesrv.sh
```

环境变量都有默认值，生产由 `homesrv/lib.sh` 统一导出；完整清单见 [`linux/README.md`](./linux/README.md#环境变量)。

## 状态矩阵

最近一次全量实测 2026-10-23（Ubuntu 24.04 / headless sway / 1280×720）。

| 能力 | 状态 | 依据 |
| --- | --- | --- |
| 启动链（sway + Chrome + 云会话 + 登录/排队/月卡/标题页） | 可用 | 全量 9/9，12 分 24 秒 |
| 日常 9 项（WebStartGame / VisitFriends / DijiangRewards / CreditShoppingN2 / AutoStockpile / AutoStockStaple / SellProduct / DailyRewards / DeliveryJobs） | 可用 | 同上，逐项耗时见 `CHANGELOG-web.md` |
| 退出与收尾（ESC 链、关进程、残留计数） | 可用 | `__ScenePrivateAnyExit` ESC×6；`homesrv/lib.sh` 的 `mh_cleanup` |
| 云版传送链（无传送点列表，点锚点 → 传送胶囊 → 等 LOADING） | 可用 | 2026-11-04 日志：OCR 0.999974 → 模板 0.958905 → LOADING 0.992 |
| AutoEssence 基质 | 未通过 | 卡 `GotoTriggerPointMove_VFTheHub`：`custom action target rect is empty`，约 82 秒后 Failed |
| EnvironmentMonitoring 环境监测 | 未通过 | 卡地图锚点 `__ScenePrivateMap*EnterWorldAnchorWithPick`，模板侧命中正常 |
| 分层地图切换 `SceneMapLayerSwitchToMain` | 未验证 | 分层地图（如「首墩内部」）缩小态还没取到图 |

控制器两种，生产只用第一种：

| 控制器 | 实现 | 用途 |
| --- | --- | --- |
| `wlroots`（默认） | 合成器 `wlr-screencopy` + 虚拟键鼠 | 生产路径，homesrv 与 cron 都走它 |
| `cdp` | 云串流 `<video>` 原生帧 + CDP 注入 | 仅 WSL / 调试；锐度高但多一层浏览器依赖，见 `docs/cdp-native-capture.md` |

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/README.md`](./docs/README.md) | 文档索引与阅读路线 |
| [`docs/architecture.md`](./docs/architecture.md) | 分层、依赖规则、资源分层、数据流、选型镜像 |
| [`docs/deployment.md`](./docs/deployment.md) | 部署布局、日常入口、自动更新、回滚、故障恢复 |
| [`docs/troubleshooting.md`](./docs/troubleshooting.md) | 已知问题 → 诊断命令 → 结论 |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | 规范来源、测试命令、提交与 PR 流程 |
| [`CHANGELOG-web.md`](./CHANGELOG-web.md) | 变更留档（Keep a Changelog） |

## 与上游的关系

- 基线跟着上游发行版走（本轮 `v2.35.0-beta.1`，`homesrv/auto_update.sh` 每天检查）。任务逻辑全部来自上游 `assets/resource`；本仓库只加「网页端与 PC 客户端不同」的薄覆盖。
- 上游 `feat/web-linux-layer` 是这条线的参考实现。`homesrv/auto_update.sh` 每天跟进发行版，且**不碰** `web/`。
- 选型镜像：截图、输入、寻路用 C++（`Linux-Wlroots` 控制单元、`agent/cpp-algo`），业务动作用 Go（`agent/go-service`），Python 只做编排与状态，不写像素与坐标计算。

> [!NOTE]
> 资源层的迁移（`web/resource_web` → `assets/resource_cloud_web/`）已经落库：`assets/interface.json` 用 `attach_resource_path` 挂新路径，部署脚本 `homesrv/lib.sh` 优先用新路径、找不到时回落旧路径。显式设置 `MAAEND_RES_DIRS` 时以环境变量为准，具体顺序见 [`linux/README.md`](./linux/README.md#环境变量)。
