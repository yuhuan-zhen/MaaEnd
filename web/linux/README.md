# web/linux —— 运行层

本目录是 [`web/`](../README.md) 的运行层：任务编排、控制器与 agent 生命周期、页面状态、恢复、部署脚本。上游 `assets/` 提供任务逻辑与资源，这里只负责「在无桌面的 Linux 上把它跑起来、跑挂了能自己爬起来」。

## 分层

```text
cli      maaend_web/cli/           入口：参数解析、任务选择、结果汇总、退出码
runtime  maaend_web/*.py           与框架 / 浏览器 / CDP / 系统交互
core     maaend_web/*.py           纯逻辑：配置、预设、计划、结果、JSONC
```

依赖方向单向：`cli → runtime → core`。`core` 不 import `maa`，因此预设解析、计划筛选、结果落盘换台机器也能单测。

| 模块 | 层 | 职责 |
| --- | --- | --- |
| `maaend_web/config.py` | core | 路径、环境变量、端口、任务超时的**单一真源**；`Settings` 构造后不可变 |
| `maaend_web/preset.py` | core | MXU 预设 → `pipeline_override`：选项树递归展开、占位符按 `pipeline_type` 转型 |
| `maaend_web/plan.py` | core | `--tasks` / `--only` / `--from --to` 的任务选择 |
| `maaend_web/results.py` | core | 逐任务结果落 JSONL + 汇总文本 |
| `maaend_web/jsonc.py` | core | JSONC 读取：先按标准 JSON 解析，失败再去注释与尾逗号 |
| `maaend_web/framework.py` | runtime | `LD_PRELOAD` 自愈、控制器选择、go-service / cpp-algo 生命周期、tasker 配置 |
| `maaend_web/recovery.py` | runtime | 进世界判定、恢复节点链、硬重置、失败现场帧 |
| `maaend_web/page.py` / `page_control.py` | runtime | 页面状态机（九态求值 → 分支 → 动作）与页面控制 |
| `maaend_web/page_js.py` | runtime | 页面侧 JS 源码；Python 与 node 测试共用同一份 |
| `maaend_web/overlay.py` | runtime | 浮层策略：注入 + 探测 + 文档替换后自愈 |
| `maaend_web/cli/` | cli | `daily.py`（日常）、`overlay.py`（浮层） |

顶层的 `run_daily_linux.py`、`resolve_preset.py`、`page_state.py`、`overlay_ctl.py`、`cdp_controller.py` 是**兼容 shim**：生产 cron 与环境变量路径不变，实现都在 `maaend_web/`，shim 只做转交。`cdp_controller.py` 指向的 CDP 控制器已移入 `devtools/`，不在生产路径上。

## 目录

| 路径 | 作用 |
| --- | --- |
| `maaend_web/` | 运行层包，见上表 |
| `devtools/` | 非生产工具：`cdp.py`（云串流原生帧控制器）、`wsl/`（WSL 调试环境）、抓帧与模板重录脚本 |
| `homesrv/` | 部署层，见下节 |
| `tests/` | `test_*.py` + `*.test.mjs`，全部离线可跑 |
| `resource_web_linux/` | 网页端 Linux 层模板覆盖：字体光栅化与 Windows 不同，同一个按钮要在 Linux 帧上重抠（现在只剩 `WebStartGame/StartButton.png`） |

## 系统依赖

发行版本身只需要 Python，但两条控制器路径各有额外的**系统库**要求；新机器上缺了会在
启动阶段报 `cannot open shared object file`。以下都是实测结论：

| 依赖 | 谁需要 | 装法 | 缺失时的表现 |
|---|---|---|---|
| `libpipewire-0.3.so.0` | wlroots 控制单元 | `dnf install pipewire-libs` / `apt install libpipewire-0.3-0` | `libMaaLinuxControlUnit.so` dlopen 失败 |
| `libei.so.1` | wlroots 控制单元 | `apt install libei1`；**RHEL 8 系与 EPEL 8 都没有**，需 RHEL 9+ / Ubuntu 24.04+ | 同上，`ControlUnitLoadError` 会点名这个库 |
| `libMaaFramework.so`、`libonnxruntime.so.1` | go-service | 随 MaaFw wheel 提供，铺到 `agent/maafw/` | agent 起来后立刻 FTL 退出，`agent connect` 一直卡住 |
| `libc++.so.1`、`libc++abi.so.1` | cpp-algo | **只有官方 Linux release 的 `maafw/` 目录带** | `cpp-algo: error while loading shared libraries` |
| Chrome / Chromium | cdp 控制器 | 任何支持 `--remote-debugging-port` 的构建 | `URLError: Connection refused` → `screencap failed` |
| OpenCV 3.x+ | 仅 cpp-algo 源码编译 | `dnf install opencv-devel` | 链接失败 |

两个容易连踩两遍的点：

- **`*.so` 通配符抓不到带版本号的库**。`libonnxruntime.so.1`、`libc++.so.1` 这类只有
  `*.so*` 能匹配上；漏了它们，agent 启动时一次只报第一个缺失项，修一个冒一个。
- **cpp-algo 不用系统 libc++ 编译**。MaaUtils 的 `config.cmake` 强制找 `libc++.so.1`，
  并用 clang 的 `-target` 参数（g++ 直接报 `unrecognized command-line option '-target'`），
  而 RHEL 8 系没有 `libcxx-devel`。直接取官方 Linux release 里的预编译 `agent/cpp-algo`
  并让 `agent/maafw/` 用该 release 自带的那份库，比在本地凑工具链省事得多。

Python：`requires-python` 声明 `>=3.14`，但实测 **3.11 即可跑通全部离线单测**
（代码只用到 3.10 的 `X | None` 写法）。只能装到 3.11 的发行版不必为此折腾。

## 部署脚本

| 脚本 | 作用 |
| --- | --- |
| `homesrv/lib.sh` | 公共层：cron 会话变量、日志轮转、启动浏览器、等 CDP、页面归位、浮层自检、收尾（`trap` 保证失败与中断也清理） |
| `homesrv/deploy.sh` | 一键部署：备份 → 同步 → 语法检查 → 叠回覆盖层 → `--dry-run` 自检 → 打印回滚命令；支持 `--dry-run` / `--remote HOST` / `--dest` |
| `homesrv/daily_run_homesrv.sh` | 一键日常：起环境 → 按预设跑 → 收尾 |
| `homesrv/essence_run_homesrv.sh` | 基质独立链：多轮 `WebStartGame,AutoEssence`，成功 N 轮即停 |
| `homesrv/nightly_run_homesrv.sh` | 夜间总调度（cron 一条）：`auto_update` → 日常 → 基质，三步串行避免抢同一份 Chrome profile |
| `homesrv/chrome_homesrv.sh` | 起 headless sway + Chrome（复用部署机上的 Chrome for Testing） |
| `homesrv/auto_update.sh` | 跟进发行版：`--check` 只看版本、`--force` 版本相同也重装；替换后自检，失败自动回滚 |
| `homesrv/stop_homesrv.sh` | 停掉在跑的任务并完整收尾，35 秒后复验「杀完又起来」 |
| `homesrv/overlay_apply.py` + `overlay_ops.json` | 升级 / 部署后把仓库侧的覆盖层叠回部署树（幂等），`auto_update.sh` 与 `deploy.sh` 都调它 |
| `homesrv/post_upgrade_check.py` | 升级后自检：关键节点与资源是否还在 |
| `homesrv/option_audit.py` + `option_baseline.json` | 覆盖项基线审计：升级后选项树漂移检测 |
| `homesrv/map_probe.py` | 地图界面节点级探针（诊断用） |
| `homesrv/set_geometry.sh` + `geometry.conf` | 窗口几何与分辨率 |

浮层隐藏走 `overlay_ctl.py --watch`（容器级抹平在 `page_js.FLATTEN_JS`，`homesrv/hide_cloud_ball.py` 与 `hide_cloud_overlay.py` 是历史入口）。

## 运行

```bash
# 只打印计划，不连控制器
MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --dry-run

# 单任务（外层已有重试链时用 --attempts 1，避免叠加）
MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --tasks WebStartGame --attempts 1

# 全量日常（homesrv 生产入口，含启动 / 收尾 / 日志轮转）
bash web/linux/homesrv/daily_run_homesrv.sh

# 基质独立链
bash web/linux/homesrv/essence_run_homesrv.sh
```

`--dry-run` 只读预设，仍然需要一份 MXU 预设文件（默认 `$MAAEND_ROOT/config/mxu-MaaEnd.json`）；没有预设时用 `--help` 验证入口可用。

## 环境变量

全部有默认值，生产由 `homesrv/lib.sh` 统一导出。默认值只在 `maaend_web/config.py` 拼装，其他模块不再自己 `os.environ.get`。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MAAEND_DIST` / `MAAEND_ROOT` | `~/maaend` | 发行版根目录（`resource/`、`interface.json`、`agent/`）；前者优先 |
| `MAAEND_WEB` | `<root>/web` | 本目录的部署位置 |
| `MAAEND_RES_DIRS` | 自动探测 | 冒号分隔的资源层；给了就不再做存在性过滤，缺失层由 runtime 逐条提示 |
| `MAA_LOG_DIR` | `~/maaend-log` | 框架日志目录，必须可写 |
| `MAA_AGENT_BIN` | `<root>/agent/go-service` | go-service 可执行文件 |
| `MAA_AGENT_LIB` | `<agent>/maafw` | agent 的 `LD_LIBRARY_PATH` |
| `MAAEND_WEB_CDP_PORT` | 自动 | Chrome DevTools 端口；未设置时先用 9334，被占用则由 Chrome 自选并写入 `$PROFILE/.maaend_cdp_port`（Python 与 shell 都读这个文件） |
| `MAAEND_SESSION_TAG` | `endfield-web` | 浏览器进程标记（`--maaend-session=`）；收尾按它精确匹配，多实例互不误杀 |
| `WLR_SOCKET` | 自动探测 | wayland socket；按 `XDG_RUNTIME_DIR` → `/tmp/xdg-run/wayland-1` → `/run/user/<uid>/wayland-1` 顺序找 |

部署脚本另读：`MAAEND_TASKS`（临时覆盖任务列表）、`MAAEND_PROFILE`（Chrome profile）、`MAAEND_CHROME`（浏览器路径）、`MAAEND_ESSENCE_OK` / `MAAEND_ESSENCE_MAX` / `MAAEND_ESSENCE_SLEEP`（基质链的成功轮数、尝试上限、重试间隔）。

## 测试

```bash
# Python：预设解析、计划筛选、配置、页面状态机、浮层判定（不需要 maa）
python -m unittest discover -s web/linux/tests -v

# JS：页面状态判定、输入策略、覆盖层分层（与 Python 共用 page_js.py 的源码）
node --test web/linux/tests/*.test.mjs
```

## 已知限制

- 云版地图没有「传送点列表 / 确认框」，传送链按「点锚点 → 点传送胶囊 → 等 LOADING」重写。
- cpp-algo 必须停在 1.0856 版（3.86 units/度）；发行版自带的新版按 7.93 units/度算，导航会 2 倍超调、永不收敛。
- 指针累计到视口边缘后 `post_relative_move` 仍返回成功但画面不动，长时间任务前需要回中。
- Chrome 用 SwiftShader 软渲染，2560×1440 会让 gpu-process 跑到 599% CPU；720p 约 79%。
- 截图长边被 MaaFramework 缩到 1280，模板必须按 1280×720 标；`set_screenshot_target_long_side()` 可改，但要重标模板。
- 取帧失败没有退避：框架按固定间隔立即重试。无游戏画面时实测 80 秒内重试 8 万次、写出 40 MB 日志，长时间空转会写满磁盘——外层要配日志轮转。

## 相关文档

- 总入口与状态矩阵：[`../README.md`](../README.md)
- 分层与依赖规则：[`../docs/architecture.md`](../docs/architecture.md)
- 部署、回滚、自动更新：[`../docs/deployment.md`](../docs/deployment.md)
- 已知问题与诊断命令：[`../docs/troubleshooting.md`](../docs/troubleshooting.md)
