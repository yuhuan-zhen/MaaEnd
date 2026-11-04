# 云·终末地 Linux 运行层：项目化重构方案（2026-11-04，第二轮）

> 本文是本轮**唯一契约**。所有子任务共用这里的目录结构、模块边界、文件所有权与验收标准。
> 与本文冲突时，先改本文再改代码。第一轮契约见同目录上一级的 `../refactor-20261104/PLAN.md`（已完成，勿重复）。

## 1. 基线与上游参考（强制）

| 角色 | 路径 | commit | 说明 |
| --- | --- | --- | --- |
| **我们的分支** | `D:\maaend-upstream` | `feat/web-linux-project-20261104` ← `b8cda0c66` | 本轮唯一工作树；fork `yuhuan-zhen/MaaEnd` |
| **官方 MaaEnd（第一参考）** | `D:\maaend-official`（只读 worktree） | `ba5887d64` = `upstream/v2` | 结构、命名、pipeline 写法、Python 风格全部以此为准 |
| **官方 MaaFramework** | `D:\MaaFramework` | `0fc6025`（main） | 控制器、取帧、输入、Pipeline 协议的权威实现 |
| 仓库内规范 | `<我们的分支>/.agents/skills/<name>/SKILL.md` | — | 16 个 skill，按方向精读 |
| 生产部署 | homesrv `~/maaend` | `master@4e98104` + 70 改动 | 只读参考，本轮不直接改 |

**铁律：不得把 fork 上的 `web/linux` 当「上游参考」**（那等于参考自己）。凡本文写「参考上游」，只指 `D:\maaend-official` 与 `D:\MaaFramework`。

**第一轮解决了「能不能维护」，本轮解决「别人能不能用、改了怎么验证、错在哪查」**。

## 2. 技术选型镜像规则（用户明确要求）

**上游用什么语言实现同类能力，我们就用什么语言，不得自造替代实现。**

| 能力 | 上游实现 | 语言 | 我们的做法 |
| --- | --- | --- | --- |
| 截图 / 输入注入 / 控制器 | `D:\MaaFramework\source\MaaLinuxControlUnit\`（`WlrScreencap`/`PipeWireScreencap` + `WlrInput`/`UInput`/`EiInput`） | **C++** | 直接用框架 controller（`Linux-Wlroots`），不写 Python 控制器做主路径 |
| 寻路 / 移动 / 地图定位 | `D:\maaend-official\agent\cpp-algo\source\{MapNavigator,MapLocator,Navmesh}\` | **C++** | 调用 `agent/cpp-algo`；不在 Python 里重写转向/寻路 |
| 图像识别 / 模板匹配 / 颜色 | 框架 C++ + `agent/cpp-algo/IconRecognition` | **C++** | 用 pipeline 节点或 cpp-algo 自定义识别 |
| 业务动作 / 识别扩展 | `D:\maaend-official\agent\go-service\<业务>\` | **Go** | 需要扩展就在 `agent/go-service/` 加包并在 `registerAll()` 注册 |
| 开发工具 / 数据生成 / schema / 测试 | `D:\maaend-official\tools\**`（`tools/<Name>/main.py` + `[project.scripts]`） | **Python** | 工具类放 `tools/`，每工具一包 + `main.py` |
| 运行层编排（任务计划/恢复/配置） | **上游无对应物**（MaaEnd 不做网页端 Linux 运行层） | Python（唯一合理） | 留在 `web/linux/maaend_web/`，文档标注「无上游对应」 |

**结论性动作**：

1. `web/linux/maaend_web/cdp.py`（628 行 Python CDP 控制器）不是主路径（生产走 C++ `Linux-Wlroots`）→ 移到 `web/linux/devtools/`，docstring 标「仅 WSL/调试，非生产」。
2. 取帧/输入/寻路不得新增 Python 实现；要扩展就改 `agent/go-service/`（Go）或提 MaaFramework（C++）。
3. 我们的 Python 只做「编排与状态」，不做「像素与坐标计算」。

## 3. 结构与风格对齐（逐项照抄官方）

| 项 | 官方做法（ba5887d64 实测） | 我们现状（要改） |
| --- | --- | --- |
| 资源分层 | `assets/resource`(PC base) / `resource_adb` / `resource_cloud` / `resource_linux` / `resource_macos` / `resource_playcover`，平台差异各薄覆盖 | `web/resource_web` + `web/resource_web_homesrv` + 4 套实验目录，命名位置都不合范式 |
| Controller 挂载 | `assets/interface.json` 的 `controller[].attach_resource_path` 声明该平台加载哪些资源层 | 我们靠 `MAAEND_RES_DIRS` 四层深合并，绕开官方机制 |
| 云层命名 | 官方已把 `resource_cloud_adb` **改名** `resource_cloud` | 我们基线仍是 `resource_cloud_adb`（旧名） |
| Pipeline 组织 | 按业务分目录：`pipeline/AutoEssence/CommonNodes/Capacity.json`、`pipeline/DailyRewards/Event/TitleYellow.json`…，单文件 1–7 节点 | 36 节点全塞 `pipeline/nodes.json` |
| Pipeline 格式 | **JSONC**：14 个云层文件全部含 `//` 注释与 `// @i18n-skip` | `split_overlay.py` 用严格 `json.load`，注释会被拒 |
| Python 版本 | `requires-python = ">=3.14"`，`ruff target-version = "py314"` | 我们写 py312 |
| Python 风格 | **129 个 py 文件 0 个用 `from __future__ import annotations`**；120 列；`select=[B,C4,E4,E7,E9,F,I,RUF,SIM,UP,W]`；模块 docstring 写「背景 + 退出码 + 用法」；`pathlib.Path` 优先 | 大量 `from __future__`、py312 写法 |
| 工具结构 | `tools/<Name>/` 包 + `main.py` + `[project.scripts]` + PEP 723 头 | 平铺 `web/linux/*.py` |
| 任务注册 | `assets/tasks/*.json` 由 `interface.json` 的 `import` 数组挂载（71 条） | `web/tasks/WebStartGame.json` **未注册** |
| 测试 | `tests/<业务>/` 目录 | 我们单层 `tests/test_*.py`（可保留，新增按业务分目录） |

**官方云层实测**：`assets/resource_cloud/` = 14 个 JSON / 27 节点；`assets/resource_linux/` = 2 个 JSON / 7 节点。平台层是**很薄**的覆盖，不是大批量替换。

## 4. 体检结论（本轮要修的事实）

| # | 问题 | 量化证据 |
| --- | --- | --- |
| 1 | **零 CI**：`.github/workflows/` 26 个 workflow 无一覆盖 `web/**` | `grep -rl "web/" .github/workflows/` → 空 |
| 2 | **私有化痕迹 52 处 / 31 文件**：`/mnt/d/...`、`/root/maaagent`、`D:/桌面`、`hmuddz8`、`hyasuml` | `grep -rn -E "/mnt/d\|/root/maaagent\|D:/\|hmuddz8\|hyasuml" web/` |
| 3 | **5 套资源目录并存**：`web/resource_web`(32 节点) + `web/resource_web_homesrv`(5) 是生产；`web/linux/resource_web_{min,startup,structural,cdp}`(14/14/3/1 节点) 是实验残留 | `find web -name nodes.json` |
| 4 | **13 个节点与官方 `resource_cloud` 重名**（疑似重复造轮子）；13 个真正独有；10 个覆盖 base | `docs/project-20261104/node-overlap.txt` |
| 5 | **两套 README 互相矛盾**（`web/README.md` 73 行描述平铺结构，`web/linux/README.md` 84 行描述包结构），`CHANGELOG-web.md` 停在 2026-10-23 | 逐行对比 |
| 6 | **runtime 模块无测试**：`framework/recovery/results/cdp/jsonc` 五个模块 0 覆盖 | `ls web/linux/tests` |
| 7 | **任务定义分散**：`web/tasks/WebStartGame.json` 需人工 import 到 `assets/interface.json`；`web/tasks/pretasks/` 空目录 | `ls web/tasks` |
| 8 | **`wsl/` 27 个开发工具与生产代码同层**，`cdp_controller.py` 只在 docstring 里提它 | `ls web/linux/wsl` |
| 9 | **部署态与仓库脱节**：homesrv 工作区 70 个改动未入库 | homesrv `git status --short \| wc -l` |

## 5. 目标形态

```text
assets/
├── interface.json                    # 加网页端资源挂载（优先复用 Linux-Wlroots 的 attach_resource_path）
├── resource/                         # 上游 base，不动
├── resource_cloud/                   # 跟随官方改名（原 resource_cloud_adb）
├── resource_linux/                   # 上游 Linux 薄覆盖，不动
└── resource_cloud_web/               # 新增：网页端薄覆盖（原 web/resource_web，按业务分目录）
    ├── pipeline/
    │   ├── SceneManager/SceneLogin.json      # 启动/排队/月卡/标题页
    │   ├── SceneManager/Exit.json            # ESC 退出链
    │   ├── SceneManager/MapTeleport.json     # 云版传送链
    │   ├── Common/Button/ButtonColor.json
    │   ├── DailyRewards/Event.json
    │   ├── AutoStockStaple/Item.json
    │   ├── AutoEssence/Capacity.json
    │   ├── EssenceFilter/Tab.json
    │   ├── ItemTransfer/Repo.json
    │   └── OutpostTrading/SellCore.json
    └── image/<同名分层>/*.png

web/
├── README.md / CONTRIBUTING.md / CHANGELOG-web.md / pyproject.toml
├── docs/{README,architecture,deployment,troubleshooting}.md
├── docs/project-20261104/PLAN.md
├── docs/diagnostics/
├── linux/
│   ├── maaend_web/           # core(不 import maa) / runtime / cli
│   ├── *.py                  # 兼容 shim + 薄 CLI
│   ├── devtools/             # 新增：cdp 控制器 + wsl 27 个工具（非生产）
│   ├── homesrv/              # 部署层
│   └── tests/
└── tasks/                    # 网页端任务定义（并在 interface.json 注册）
```

**删除**：`web/linux/resource_web_{min,startup,structural,cdp}/`、`homesrv/hide_cloud_ball.py`、`homesrv/hide_cloud_overlay.py`、`web/resource_web/pipeline/__pycache__`、`web/resource_web/pipeline/patch_*.py`（一次性 patch 脚本）。
**迁移**：`web/resource_web/**` → `assets/resource_cloud_web/**`（按业务分目录）；`web/linux/wsl/**` → `web/linux/devtools/wsl/**`；`cdp.py` → `web/linux/devtools/cdp.py`。

## 6. 分层与依赖规则（不可违反）

1. **单向依赖**：`cli → runtime → core`。`core` 模块（`config/jsonc/preset/plan/results`）**不得 import `maa`**，保持可离线单测。
2. **单一真源**：路径/端口/超时只在 `maaend_web/config.py`；ruff 规则只在 `pyproject.toml`；资源分层只在 `docs/architecture.md` 描述一次。
3. **生产入口路径不变**：`web/linux/run_daily_linux.py`、`homesrv/*.sh` 的调用方式、环境变量名、rc 语义不得改（第一轮 §5 规则继续有效）。
4. **不新增第三方运行期依赖**：只用标准库 + `maa`（运行期）+ 可选 `PIL`。开发期可加 ruff/pytest 类工具，但单测必须 `unittest` 可跑。
5. **文档只由 sa-5 写**：其他组把文档需求写进交付报告，不直接改 `.md`（避免 6 个代理同时改 README）。

## 7. 子任务与文件所有权

每个子代理**只能写自己名下的文件**；跨边界改动写进报告由主代理裁决。**不要执行任何 git 命令**（主代理统一提交）。

### sa-1 资源层重组（最高优先级，其余组依赖它的路径）

| 项 | 内容 |
| --- | --- |
| 可写文件 | `assets/resource_cloud_web/**`（新建）、`web/resource_web/**`、`web/resource_web_homesrv/**`、`web/linux/resource_web_{min,startup,structural,cdp}/**`（删除）、`assets/resource_cloud_adb/**`（改名）、`assets/interface.json`（仅 `resource` / `controller` 段）、`web/tasks/**`、`docs/project-20261104/node-overlap.txt` + `pipeline-migration.md` |
| 必读规范 | `.agents/skills/pipeline-guide/SKILL.md` + `field-reference.md`；`D:\maaend-official\AGENTS.md` |
| 上游参考 | `D:\maaend-official\assets\resource_cloud\**`（14 文件 27 节点）、`assets\resource_linux\**`（2 文件 7 节点）、`assets\interface.json` 的 `controller[].attach_resource_path` |
| 任务 | ① **逐节点 diff** 我们的 36 节点 vs 官方 `resource_cloud` 27 节点：同名不等于同实现，比字段值；完全相同→删；有差异→保留并在报告说明差异点。② 13 个独有节点（`Web*`、`*CursorPark`）保留，按业务归入新目录。③ 10 个覆盖 base 的节点逐个判定「云版 UI 差异（保留）/ 本地修复（保留并标 upstream-candidate）/ 应回上游（删）」。④ 按官方粒度重建 `assets/resource_cloud_web/pipeline/<业务>/<模块>.json`，单文件 1–7 节点。⑤ `resource_cloud_adb` → `resource_cloud` 跟随官方改名，同步 `interface.json`。⑥ 在 `interface.json` 给 `Linux-Wlroots` 的 `attach_resource_path` 加 `./resource_cloud_web`（优先不新增 controller）。⑦ 删 4 套实验目录、`__pycache__`、一次性 patch 脚本。⑧ 输出 `node-overlap.txt`（节点级对照）与 `pipeline-migration.md`（迁移映射） |
| 验收 | 节点总数 = 36 − 删除数，且每个保留节点 JSON 逐键等于迁移前；全部 JSONC 可解析；`web/tasks/WebStartGame.json` 已进 `interface.json` 的 `import` |

### sa-2 运行层 Python 结构

| 项 | 内容 |
| --- | --- |
| 可写文件 | `web/linux/maaend_web/**`、`web/linux/*.py`（**除** `split_overlay.py`、`homesrv/*.py`）、`web/linux/devtools/**`（新建） |
| 必读规范 | `D:\maaend-official\AGENTS.md`、`docs/zh_cn/developers/coding-standards.md`、`D:\maaend-official\pyproject.toml` 的 ruff 段 |
| 上游参考 | `D:\maaend-official\tools\**`（129 个 py，风格与结构基准）、`tools\MapNavigator\**`（包结构）、`D:\MaaFramework\source\MaaLinuxControlUnit\**`（C++ 控制器能力边界） |
| 任务 | ① **风格全面对齐官方**：删所有 `from __future__ import annotations`、`target-version` 改 py314、docstring 按官方格式（背景+退出码+用法）。② `cdp.py` 移入 `devtools/cdp.py`，docstring 标「非生产，仅 WSL/调试；生产走 C++ Linux-Wlroots」。③ `wsl/` 27 个 → `devtools/wsl/` + README。④ 18 个顶层 `.py` 分类表（shim/薄 CLI/工具/死代码），死代码删除。⑤ 补 `tests/test_{framework,recovery,results,jsonc}.py`（stub，不连真实框架）。⑥ 清理本组硬编码（`/mnt/d`、`D:/`、`/root/maaagent`）。⑦ 把对 README 的修改需求写进报告（不改 md） |
| 验收 | `uv run ruff check web/linux` 0 error；`python -m unittest discover -s web/linux/tests` 全过且用例 ≥129；`grep -rn "from __future__" web/linux/maaend_web` 为空；无 maa 环境可 `import maaend_web.config` |

### sa-3 部署层

| 项 | 内容 |
| --- | --- |
| 可写文件 | `web/linux/homesrv/**` |
| 必读规范 | ShellCheck（`shellcheck -x`）、`docs-guide`（只读，不写 md） |
| 上游参考 | `D:\maaend-official\tools\setup\{build_and_install,setup_workspace}.py`（官方部署的分步与退出码风格）、`D:\maaend-official\install\` 的产物布局 |
| 任务 | ① 判定 `hide_cloud_ball.py` / `hide_cloud_overlay.py` 是否死代码（查 `lib.sh`/`chrome_homesrv.sh`/cron 全部引用），死则删并同步 `lib.sh` 的 pkill 列表；② `auto_update.sh` 加「升级后叠回仓库 tasks 与覆盖层」机制（遗留 5），失败要响铃不静默；③ 新增 `deploy.sh`：一键部署到 `~/maaend`（备份→同步→语法检查→dry-run 自检→回滚命令打印），符合「双击完成」偏好；④ 本组文件硬编码清理；⑤ `lib.sh` 收尾逻辑核对（`chrome=0 agent=0 sway=0` 判定） |
| 验收 | `bash -n web/linux/homesrv/*.sh`；`shellcheck -x web/linux/homesrv/*.sh` 零告警；`deploy.sh --dry-run` 不触碰生产即可跑通 |

### sa-4 任务定义与 go-service 注册

| 项 | 内容 |
| --- | --- |
| 可写文件 | `web/tasks/**`、`assets/tasks/pretasks/**`（新增文件）、`agent/go-service/**`（仅注册相关）、`web/linux/split_overlay.py` |
| 必读规范 | `.agents/skills/pipeline-guide/SKILL.md`、`.agents/skills/go-service-guide/SKILL.md`、`docs/zh_cn/developers/coding-standards.md` |
| 上游参考 | `D:\maaend-official\agent\go-service\`（`registerAll()` 与业务包）、`D:\maaend-official\assets\tasks\**`、`assets\interface.json` 的 `import`、`D:\maaend-official\tools\i18n\sync_ocr_expected.py`（OCR expected / `@i18n-skip` 规则） |
| 任务 | ① 遗留 2：`tasks/pretasks/GameSetting.json`（或 `web/tasks/pretasks`）未被 import、go-service 未注册 `GameSetting` —— 二选一：补注册（按现有 pretask 写法）或删除未用文件，给依据；② 遗留 3：`WebSessionBusy ↔ WebStartGameEntry` 无 `max_hit` 的环，评估弱网弹窗场景，必要时加 `max_hit`；③ 遗留 4：`split_overlay.py` 用严格 `json.load` 读 pipeline，导致 4 处 OCR 正则无法加 `@i18n-skip` 注释 —— 改用 `maaend_web.jsonc.load_jsonc`，然后给那 4 处补注释；④ 保证 `web/tasks/WebStartGame.json` 能被 `interface.json` import 后的 schema 通过 |
| 验收 | `python -c "import json"` 全部任务文件可解析；`split_overlay.py` 对新旧两版文件输出逐字节一致；go-service 若有改动，`cd agent/go-service && go build ./...` 通过 |

### sa-5 项目骨架（CI + 文档）

| 项 | 内容 |
| --- | --- |
| 可写文件 | `web/README.md`、`web/linux/README.md`、`web/CHANGELOG-web.md`、`web/CONTRIBUTING.md`、`web/docs/**`（除 `refactor-20261104/`、`cloud-web-20261026/` 的历史文件）、`web/pyproject.toml`、`.github/workflows/web-linux.yml` |
| 必读规范 | `.agents/skills/docs-guide/SKILL.md`（markdownlint 规则）、仓库根 `.markdownlint*`、`AGENTS.md` |
| 上游参考 | `.github/workflows/{lint,check,test,format}.yml` 的 trigger/paths/setup 写法；`web/README.md` 与 `web/linux/README.md` 现行内容 |
| 任务 | ① 新增 `.github/workflows/web-linux.yml`：仅 `web/**` 变更触发，job 分 ruff / unittest / node-test / shellcheck / markdownlint / prettier，全部可在 ubuntu-latest 跑（不依赖真实游戏环境）；② 两份 README 合一：`web/README.md` 是总入口（含架构图、安装、跑法、状态矩阵、目录表），`web/linux/README.md` 只讲运行层细节并回链；③ 新增 `docs/architecture.md`（分层 + 依赖规则 + 数据流）、`docs/deployment.md`（部署/回滚/自动更新/故障恢复）、`docs/troubleshooting.md`（已知问题 → 诊断命令）、`docs/README.md`（索引）；④ `pyproject.toml` 收编 ruff 配置（删 `web/ruff.toml` 或改为 extend）；⑤ `CONTRIBUTING.md`：规范来源表（16 个 skill）、测试命令、Conventional Commits、PR 流程；⑥ `CHANGELOG-web.md` 改 Keep a Changelog 结构，历史内容不删，追加本轮；⑦ 全仓 `web/**/*.md` 过 markdownlint |
| 验收 | `npx markdownlint-cli2 "web/**/*.md"` 或仓库现用命令零报错；workflow YAML 用 `actionlint` 或 `python -c "import yaml"` 可解析；README 里的每条命令都能在仓库根直接执行（不存在的命令删掉） |

### sa-6 诊断（只读 + 输出脚本，不改生产）

| 项 | 内容 |
| --- | --- |
| 可写文件 | `web/docs/diagnostics/**`（新建）、`web/linux/homesrv/diagnose_*.py`（新建，只读诊断） |
| 必读规范 | `.agents/skills/map-navigator-guide/SKILL.md`、`.agents/skills/maaend-issue-log-analysis/SKILL.md` |
| 上游参考 | `D:\maaend-official\agent\cpp-algo\source\MapNavigator\**`、`assets\resource_cloud\pipeline\AutoEssence\CommonNodes\Capacity.json`、`docs/cloud-web-20261026/**` |
| **已确认事实（别再推翻）** | 2026-11-04 04:16 日志：云版传送链**已通**（`TeleportChoose` OCR 0.999974「协议传送点」→ `TeleportConfirm` 模板 0.958905 → `SceneWaitLoadingExit` 0.992）。真正失败的是 `GotoTriggerPointMove_VFTheHub`：`MapNavigateAction` 04:16:07 报 `custom action target rect is empty`，04:17:29 Failed，约 82 秒 |
| 任务 | ① AutoEssence 0/8 根因排序（pipeline 链 / 覆盖层 / cpp-algo 导航），每条给下一步验证命令。② 对照官方 `resource_cloud/pipeline/AutoEssence/` 找我们基质链的缺失节点。③ 输出 `diagnose_essence.py` / `diagnose_navigate.py`（只读抓帧+节点评分，不点击）。④ `docs/diagnostics/` 结论，每条带 `文件:行号` 或日志原文 |
| 验收 | 脚本 `python -m py_compile` 通过；结论每条都带「依据文件:行号」或「日志原文」；不修改任何 pipeline/任务文件 |

## 8. 主代理职责（不外包）

1. 分支管理、提交（Conventional Commits + 中文正文）、推送 fork。
2. 跨组冲突裁决与合并顺序。
3. 全量验收：ruff / unittest / node test / shellcheck / markdownlint / JSON 解析 / dry-run 对拍。
4. 与 homesrv 的部署态对账（哪些改动该入库、哪些是机器特有配置）。
5. 最终报告：改了什么、验证了什么、剩什么。

## 9. 全局验收（全部组交付后统一跑）

```bash
cd D:/maaend-upstream
uv run ruff check web/linux
python -m unittest discover -s web/linux/tests -v
node --test web/linux/tests/*.test.mjs
bash -n web/linux/homesrv/*.sh
shellcheck -x web/linux/homesrv/*.sh
python -c "import sys,glob;sys.path.insert(0,'web/linux');from maaend_web.jsonc import loads_jsonc;[loads_jsonc(open(f,encoding='utf-8').read()) for f in glob.glob('assets/resource_cloud_web/**/*.json',recursive=True)]"
git diff --check
```

行为对拍（homesrv）：`run_daily_linux.py --instance hmuddz8 --dry-run` 与 `docs/refactor-20261104/dryrun-baseline-20261104.txt` 逐字一致。

## 10. 非目标（本轮不做）

- **不修 AutoEssence 的功能失败**（需实机反复试跑，另立任务；本轮只出诊断）。
- **不改 cpp-algo C++ 源码**（`agent/cpp-algo/` 有未提交实验改动，不在本轮范围）。
- **不改上游 `assets/resource/pipeline` 的 base 节点**（只通过覆盖层）。
- **不引入 CI 自托管 runner**、不要求 CI 跑真实游戏。
- **不动 homesrv 生产环境**（部署与实机验证由主代理在最后一步按用户口令执行）。

## 11. 回滚

本轮全部在新分支 `feat/web-linux-project-20261104`；`git checkout feat/web-linux-refactor-20261104 -- web/` 即可回到第一轮状态。生产回滚见 `docs/deployment.md`。
