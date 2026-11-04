# 参与 web/ 的开发

`web/` 是 MaaEnd 的云·终末地网页端运行层，跟着上游 `v2` 走。本页写清「规范在哪、改哪里、提交前跑什么、PR 怎么写」，动手前先读一遍。  
最后更新：2026-11-04

## 1. 规范来源

仓库根 [`AGENTS.md`](../AGENTS.md) 是总纲，具体方向按 `.agents/skills/` 下的 skill 走。`web/` 的改动基本离不开下面 16 个：

| skill | 什么时候读 |
| --- | --- |
| [`pipeline-guide`](../.agents/skills/pipeline-guide/SKILL.md) | 写 / 改 Pipeline 节点，查协议字段与节点写法 |
| [`docs-guide`](../.agents/skills/docs-guide/SKILL.md) | 写 / 改任何 `.md`：中英文要求、GitHub 渲染陷阱、markdownlint 规则 |
| [`go-service-guide`](../.agents/skills/go-service-guide/SKILL.md) | 写 / 改 `agent/go-service` 的 Go 代码与注册 |
| [`cpp-algo-style`](../.agents/skills/cpp-algo-style/SKILL.md) | 写 / 改 `agent/cpp-algo` 的 C++ 代码与工程规范 |
| [`maa-logging`](../.agents/skills/maa-logging/SKILL.md) | 在 cpp-algo 里打日志（宏用法与级别） |
| [`meojson`](../.agents/skills/meojson/SKILL.md) | cpp-algo 里用 meojson 读写 JSON |
| [`map-navigator-guide`](../.agents/skills/map-navigator-guide/SKILL.md) | 自动寻路、地图定位、角色移动与路径导航 |
| [`maaend-issue-log-analysis`](../.agents/skills/maaend-issue-log-analysis/SKILL.md) | 分析上游 issue 与运行日志，出可复现的结论 |
| [`maaend-test-image`](../.agents/skills/maaend-test-image/SKILL.md) | 加 / 导节点识别测试截图，按仓库约定命名 |
| [`autocollect-add-route`](../.agents/skills/autocollect-add-route/SKILL.md) | 新增或改写 AutoCollect 路线 |
| [`environment-monitoring-add-route`](../.agents/skills/environment-monitoring-add-route/SKILL.md) | 新增 / 补全环境监测观察点 |
| [`item-transfer`](../.agents/skills/item-transfer/SKILL.md) | 改库存转移任务的节点 |
| [`autostockstaple-log-analysis`](../.agents/skills/autostockstaple-log-analysis/SKILL.md) | 分析 `AutoStockStapleMain` 的日志 |
| [`credit-shopping-log-analysis`](../.agents/skills/credit-shopping-log-analysis/SKILL.md) | 分析 `CreditShoppingMain` 的日志 |
| [`dmp-analysis`](../.agents/skills/dmp-analysis/SKILL.md) | 分析 Windows 崩溃转储 |
| [`perlica-style-reply`](../.agents/skills/perlica-style-reply/SKILL.md) | 需要以佩丽卡身份写文案时（不影响代码） |

编码基准是上游 [`docs/zh_cn/developers/coding-standards.md`](../docs/zh_cn/developers/coding-standards.md)；本目录的分层与依赖规则见 [`docs/architecture.md`](./docs/architecture.md)。

## 2. 目录与改动边界

| 位置 | 归谁 | 说明 |
| --- | --- | --- |
| `web/linux/maaend_web/` | 运行层 | 分包见 `docs/architecture.md`；`core` 不许 import `maa` |
| `web/linux/*.py` | 运行层 | 兼容 shim 与薄 CLI，入口路径是兼容契约，不要改名 |
| `web/linux/devtools/` | 运行层 | 非生产工具；不写进生产入口，不引入到 `maaend_web` 的依赖链 |
| `web/linux/homesrv/` | 部署层 | 只用 bash + 标准库；`shellcheck -x` 必须零告警 |
| `web/linux/tests/` | 测试 | `unittest` 与 `node:test`，不许连真实框架 |
| `assets/tasks/` | 任务定义 | 网页端任务（`WebStartGame.json`）与上游任务同目录，新增后要在 `assets/interface.json` 的 `import` 里注册 |
| `assets/resource_cloud_web/` | 资源覆盖层 | 只放「网页端与 PC 客户端不同」的节点，单文件 1–7 节点 |
| `web/docs/` | 文档 | 新增文档先登记到 `docs/README.md` |

只改自己这层：运行层的改动不要顺手改上游 `assets/resource/pipeline`，覆盖层要改就写在 `assets/resource_cloud_web/` 并在节点 `desc` 里写一句为什么。

## 3. 代码规范

- **Python**：3.14 为基线（`pyproject.toml` 的 `target-version = "py314"`），120 列，规则集 `B, C4, E4, E7, E9, F, I, RUF, SIM, UP, W`。与官方一致，新代码**不写** `from __future__ import annotations`；模块 docstring 写「背景 + 退出码 + 用法」，路径优先 `pathlib.Path`。
- **只依赖标准库**：运行期不允许新增第三方依赖；`maa` 只在 runtime 的函数体内导入。
- **Shell**：`homesrv/*.sh` 用 `set -uo pipefail`，公共逻辑进 `lib.sh`，入口脚本只保留差异；`shellcheck -x` 零告警。
- **Pipeline**：JSONC，允许 `//` 注释与 `// @i18n-skip`；坐标与模板以 1280×720 为基准；用识别节点而不是 `post_delay` 等状态。
- **文档**：中文，一段一行不按宽度折行；表格紧凑格式 `| --- |`；代码块必须带语言；节点名、路径、命令写成行内代码。

## 4. 提交前自检

在仓库根跑，六项全过再提交（CI 也是这六项）：

```bash
uv run ruff check web/linux
python -m unittest discover -s web/linux/tests
node --test web/linux/tests/*.test.mjs
shellcheck -x web/linux/homesrv/*.sh
pnpm exec markdownlint "web/**/*.md"
pnpm exec prettier --check "web/**/*.json"
```

只需要装开发依赖时：`uv sync`（ruff）与 `pnpm install`（markdownlint、prettier）。没有游戏环境也能全部跑通——这是硬要求，任何用例都不许连真实框架或真实浏览器。

跑真实链路前先 `--dry-run` 看计划，再单任务 `--tasks <名字> --attempts 1`，确认后才上全量：

```bash
MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --dry-run
MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --tasks WebStartGame --attempts 1
```

## 5. 提交信息

用 Conventional Commits，**正文写中文**，说明「为什么」和「验证了什么」，不要只写「更新文件」。

```text
fix(web/linux): 恢复链补 WebSessionBusy 的 max_hit

弱网下云会话没释放时，WebSessionBusy 会与入口互相跳转形成无上限的环，
整批任务卡在启动页。加 max_hit 5 后回到入口重试。

验证：
- python -m unittest discover -s web/linux/tests
- run_daily_linux.py --tasks WebStartGame --attempts 1（弱网复现 2 次）
```

| 类型 | 用在哪 |
| --- | --- |
| `feat` | 新增能力（节点、模块、脚本） |
| `fix` | 修缺陷 |
| `refactor` | 不改行为的结构调整 |
| `docs` | 只改文档 |
| `test` | 只改用例 |
| `ci` | 工作流、脚本化检查 |
| `chore` | 杂项（依赖、忽略规则） |

scope 用目录名：`web/linux`、`web/docs`、`resource_cloud_web`、`ci`。

## 6. PR 流程

1. 从 `v2` 切分支，分支名 `feat/web-<主题>` 或 `fix/web-<主题>`。
2. 一个 PR 只做一件事。重构与功能分开，格式化单独一个提交，别混在逻辑改动里。
3. PR 描述写四段：**改了什么**（文件与行为）、**为什么**（问题与证据）、**怎么验证**（命令与真实输出）、**风险与回滚**（影响面、怎么退）。
4. 等 `web-linux` 工作流的六个 job 全绿；红了先看日志再改代码，不要改 CI 去迁就。
5. 涉及 `assets/` 的改动会同时触发上游 `check` / `test` 工作流，那两个套件由上游 CI 负责，本地按需跑 `pnpm check`。

## 7. 不要做的事

- 不要用 `post_delay` / `sleep` 掩盖时序问题；补中间识别节点或 `pre_wait_freezes`。
- 不要在 `maaend_web/core` 里 import `maa`，也不要在模块顶层 import 框架。
- 不要把本机路径、私有实例名、代理地址写进代码或文档。
- 不要提交调试用的现场帧、日志、`probe_out/` 产物；模板图片要提交，且按 720p 裁。
- 不要为了让单测过而放宽断言；用例失败先判断是实现错了还是期望错了。
