# 变更留档

本文件记录 `web/` 的改动。格式参考 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，条目按「新增 / 变更 / 修复 / 删除」分类；版本号跟上游发行版（当前基线 `v2.35.0-beta.1`），日期为北京时间。

阅读入口：总览见 [`README.md`](./README.md)，文档索引见 [`docs/README.md`](./docs/README.md)。

## [未发布]

### 新增

- `.github/workflows/web-linux.yml`：覆盖 `web/**` 与 `assets/resource_cloud_web/**` 的六个 job——`ruff`、`unittest`、`node-test`、`shellcheck`、`markdownlint`、`prettier`。全部在 `ubuntu-latest` 上跑，不依赖真实游戏、框架或图形会话。
- `web/docs/README.md`、`architecture.md`、`deployment.md`、`troubleshooting.md`：文档索引、分层与依赖规则、部署与回滚、症状到诊断命令。
- `web/CONTRIBUTING.md`：规范来源表（16 个 skill）、提交前六项自检、Conventional Commits 与 PR 流程。
- `web/pyproject.toml`：`web/` 的 ruff 配置，用 `extend` 继承根配置，只追加 `UP031`、`SIM115` 两条豁免。

### 变更

- 两份 README 合一：`web/README.md` 做总入口（架构图、安装、跑法、状态矩阵、目录表），`web/linux/README.md` 只讲运行层细节并回链。
- 运行层收入 `maaend_web` 包（`cli` / runtime / core），顶层只留兼容 shim 与薄 CLI；调试工具迁到 `linux/devtools/`（`cdp.py`、`wsl/`）。
- 网页端资源覆盖层从 `web/resource_web` 迁到 `assets/resource_cloud_web/` 并按业务分目录；挂载改由 `assets/interface.json` 的 `controller[].attach_resource_path` 声明。
- 网页端任务定义从 `web/tasks/` 移到 `assets/tasks/`（`WebStartGame.json`），与上游任务同目录、同样由 `import` 注册。
- 本文件的格式转成 Keep a Changelog；2026-10-23 的原始记录逐条保留，只统一标题层级与代码块语言。

### 删除

- `web/ruff.toml`：规则并入 `web/pyproject.toml`，不再有第二份 ruff 配置。
- `web/linux/resource_web_{min,startup,structural,cdp}/`：实验残留的资源层。

### 未验证

- AutoEssence 仍是 0/8：卡在 `GotoTriggerPointMove_VFTheHub` 的 `custom action target rect is empty`，根因分析见 `docs/diagnostics/`。
- EnvironmentMonitoring 仍卡地图锚点；分层地图 `SceneMapLayerSwitchToMain` 还没取到缩小态的画。
- 升级后叠回仓库 `tasks/` 与覆盖层的机制需要一次真实升级验证。

## 历史留档

以下为 2026-10-23 的原始记录，按当时顺序逐条保留，只统一了标题层级与代码块语言，措辞未改。当时还要求把每次改动的文件复制一份到本机归档目录，该做法已废弃，现在以 git 提交与本文件为准。

### 2026-10-23 · WSL 调试环境从 0 到「只差标题页」

#### 结论先行

- 环境（sway + Chrome + MaaFW + agent）**已打通**：点「开始游戏」能到游戏标题页，`__ScenePrivateLogin` 命中。
- 卡点：`WebQueueDetected` 在标题页误命中（已修），修完尚未复跑到通过。
- 设计定案：**照安卓云（`resource_cloud_adb`）的做法**——云层只保留云 UI 专属节点，进游戏的登录/继续/月卡/维护一律复用 base 的 `__ScenePrivateLogin*` 链。

#### 提交记录

- `be6b2d781` WSL 调试环境入口（start_web.sh + README）
- `5b2048c10` 补回 MAA_SAVE_DRAW 识别可视化开关（与 homesrv 部署版对齐）
- `fe81fda4e` WSL 上 MXU 能跑起来的三处修正（资源条目 / socket / Chrome 语言）
- `b7206d9c2` 关掉 profile 里的翻译气泡（压住右上角 ROI）
- `3d7ac254e` 中和旧版 resource_linux 导致的「资源加载失败」
- `64e4af4e7` 「开始游戏」接成正式任务，供 MXU 预设使用
- `63b30800c` 修 MXU 白屏两处真因 + 开始游戏任务入库
- `41d6d97fc` 语言包源在仓库 assets/locales/interface
- `4084f0641` auto_update 同步 locales 与平台层
- `391320804` 「开始游戏」pipeline 方案草案 v0.1
- `7f5de1cd3` / `f78e1151c` 照抄 PC 链路（已回退，原因见下）
- `1d3ea5851` 开始游戏改为照安卓云的做法（云层薄化）
- `f3b3f6ca2` 自动接受 Chrome 原生对话框（Leave site?）
- `5ac907956` apply_wsl_setup 顺带修 agent/maafw 符号链接
- `095e02eab` WSL 日常入口每次运行前自愈装配
- `cdc78e78a` 安卓云的云 UI 节点接进启动链
- `67bc1450f` dialog 自动接受改用脚本自身路径 + nohup+setsid
- `792bae27f` WebQueueDetected 收紧判断

#### 踩过的坑（都已修，别再踩）

| 坑 | 症状 | 修法 |
| --- | --- | --- |
| MXU 自更新覆盖 base | `resource/` 被换、`interface.json` 重写、`agent/maafw` 链接被冲 | `apply_wsl_setup.py` 幂等重放，且每次运行前自动跑 |
| 新增 resource 条目 | MXU 白屏 `Object.entries … not null` | 不新增条目，改为扩充「官服」的 path |
| 手插预设任务缺 `optionValues` | 同上白屏 | 必须带 `"optionValues": {}` |
| 旧 `resource_linux` 悬空 next | 「资源加载失败」，连坐所有层 | 删悬空引用，或随包更新平台层 |
| `locales/` 落后 | 任务名显示 `task.Xxx.label` | 用仓库 `assets/locales/interface/` 覆盖 |
| `$WEB` 未定义（`set -u`） | 浏览器起不来，`line 76: WEB: unbound variable` | 用 `${BASH_SOURCE[0]}` 定位 |
| 裸 `setsid` 起子进程 | WSL 会话结束就被收，`dialog=0` | `nohup setsid` |
| `agent/maafw` 链接丢失 | go-service 报 `cannot open shared object file`，`client.connect()` 永久阻塞 | 重建链接（脚本已带） |
| `Leave site?` 原生弹窗 | 遮住标题页，点击落不到「继续」 | `auto_dismiss_dialog.py` 常驻接受 |
| `WebQueueDetected` ROI 过大 + 泛词 | 标题页被误判成排队，空等 | 收紧 ROI + 只留中文强词 + 从 Entry 移除 |

#### 待办

1. 复跑验证 `WebStartGame`：`__ScenePrivateLoginContinue` → `WebAlreadyInGame`
2. 把「打开网页端」做成任务体系的一部分（pretask `tasks/pretasks/WebLaunchBrowser.json`，用 `StartApp`），替代预设里的 preAction
3. 验证通过后接 `VisitFriends` 跑一项真实日常

### 2026-10-23 03:10 · 快照（MXU 直跑，rc.1）

状态：**网页端已能自己拉起（pretask 生效）**，MXU 侧 `merged import "web/tasks/pretasks/WebLaunchBrowser.json"` 确认。

这一轮跑出来的失败点（`debug_exports/MaaEnd-logs-v2.35.0-rc.1-20261023-031026`）：

| 任务 | 失败节点 | 次数 |
| --- | --- | --- |
| 环境监测 | `GoToIndoorCropsMove` | 9 |
| 环境监测 | `IndoorCropsQuickTeleportDone` | 3 |
| 出售 | `AutoSellFriendsPricesExpected` | on_error 截图 |
| 出售 | `AutoSellExecuteValleyIVMain` | on_error 截图 |

含义：环境监测卡在「室内作物」这条子路线的**快速传送**（`IndoorCropsQuickTeleportDone` 没命中 → 后续 `GoToIndoorCropsMove` 反复走位失败）；
出售卡在**好友价格面板**（`AutoSellFriendsPricesExpected`）与四号谷地执行节点。

待办：拉这两个节点在失败时刻的识别分数与截图，区分「没找到 UI」与「找到但点不动」；室内作物路线属可选路线，可先在预设里关掉以恢复其余项。

#### 当前装配基线（归档时）

- base：v2.35.0-rc.1（MXU 自更新）
- 资源层：`./resource` + `./web/resource_web` + `./web/linux/resource_web_linux` + `./web/resource_web_homesrv`（5 路径全 loaded=True）
- import：`web/tasks/WebStartGame.json`、`web/tasks/pretasks/WebLaunchBrowser.json`
- 7 个实例 socket 全部 `wayland-1`；`快速日常` 9 项全开
- 每次运行前 `apply_wsl_setup.py` 自愈（防 MXU 覆盖）

### 2026-10-23 03:2x · 会被覆盖的资产盘点 + 三层策略

#### 规模（WSL 现网 /root/maaend）

| 位置 | 文件数 | 大小 | 覆盖方式 |
| --- | ---: | ---: | --- |
| `resource/pipeline/nodes.json` | 1 | 3.7 MB | 整文件替换（5997 节点） |
| `resource/image/` | 2284 | 34 MB | 整目录 |
| `resource/model/` | 15 | 224 MB | 整目录（ONNX） |
| `resource_linux/` | 1 | 12 KB | 整目录 |
| `resource_adb/` | 409 | 3.5 MB | 整目录 |
| `resource_cloud_adb/` `resource_macos/` `resource_playcover/` | 各 1 | 20/24/12 KB | 整目录 |
| `locales/` | 46 | 1.6 MB | 整目录 |
| `maafw/` | 30 | 67 MB | 整目录 |
| `agent/go-service` `agent/cpp-algo` | 2 | 66 MB | 整文件（`agent/maafw` 链接会被冲掉） |
| `interface.json` | 1 | 8 KB | 整文件重写 |
| `config/mxu-MaaEnd.json` | 1 | 92 KB | MXU 每次退出全量重写 |

base 侧合计 ≈ 2790 文件 / ≈400 MB；我们自己的 `web/` 只有 45 文件 / 576 KB（全在 git 里，无人覆盖）。

#### 策略（三层）

1. **base 资产**：快照锁定，不试图阻止更新。`/root/maaend-pinned`（399 MB）+ `pin_base.sh` 版本比对，不一致整体还原。
2. **interface.json**：每次运行前用 `apply_wsl_setup.py` 重放（官服 4 层 path + 两条 web import）。
3. **config/mxu-MaaEnd.json**：只重放运行必需项，不当作持久化手段；真正的持久化在 `web/tasks/*.json`、`web/resource_web/pipeline/nodes.json`、`apply_wsl_setup.py`、`pin_base.sh`。

#### 未做（待定）

- MXU 手动点运行不经过 `daily_run_wsl.sh`，因此不触发锁版/重放；若长期用 MXU，需加 5 分钟一次的 cron 跑 `pin_base.sh`。

### 2026-10-23 03:33 · ✅ WebStartGame 首次完整通过

```text
03:30:11  开始  预设=hmuddz8 任务=[WebStartGame]
03:33:56  WebStartGame  OK  191.1s
03:33:56  通过 1 / 1   rc=0
```text

链路：起 sway/Chrome → 点「开始游戏」→ 排队/加载 → 标题页「点击任意位置继续」→ 进大世界。

凑齐的 6 处修复：`67bc1450f`（`$WEB` unbound）、`5ac907956`（agent/maafw 链接）、
`f3b3f6ca2`（Leave site? 自动接受）、`792bae27f`（WebQueueDetected 收紧）、
`1d3ea5851`（云层薄化，复用 base 登录链）、`a0605ab74`（覆盖层收敛 + 删无证据覆盖）。

#### 踩坑补记

- **MaaFw 在任务结束时会清空 draw 目录**：跑完 `ls <log_dir>/vision` 得 0，但中途有 2200 张。
  要留证据必须在跑的中途复制，或依赖 `on_error`（仅失败时保留）。

### 2026-10-23 04:0x · 「启动网页端」节点化 + 在 MXU「添加任务」可见（✅ 已验证）

#### 节点化（`43a7be738`）

```text
WebLaunchSwayStart    StartApp → start_sway.sh       （幂等：socket 在即秒退）
WebLaunchChromeStart  StartApp → start_chrome.sh     （幂等 + 对话框守护）
WebLaunchReady        识别 Or(WebLauncherStartButton, WebPageReady)
WebLaunchFailed       兜底，回 Ready 继续等（max_hit 10）
WebPageReady          OCR 用户中心/开始游戏/畅玩卡/通行证UID（右侧面板 ROI）
```text

要点：**就绪判据用识别，不用 sleep**（替代原来的 `post_delay 8000`）。sway 与 Chrome 拆两个脚本、两个节点，失败时一眼看出是哪一步没起来。

#### 任务在 MXU 里看不到的三个原因（逐个踩过）

| 现象 | 原因 | 修法 |
|---|---|---|
| 添加任务面板没有 | 放成了 **pretask**（`web/tasks/pretasks/`），pretask 不进添加面板 | 移到 `web/tasks/WebLaunchBrowser.json` |
| 移动后仍没有 | `entry` 还指节点化时删掉的 `WebLaunchBrowserStart` | entry 改 `WebLaunchSwayStart` |
| entry 修好仍没有 | `label` 用 `$task.WebLaunchBrowser.label` 但**语言包没这个键**，任务面板解析不到 label 就跳过渲染 | 五个语言包补 `task.WebLaunchBrowser.label/description`，并写进 `apply_wsl_setup.py` |

#### 附带修掉

- `interface.json` 的 import 里残留两条历史 `pretasks/` 路径（74 → 72），`apply_wsl_setup.py` 现在按片段清理
- `WebLaunchBrowser` 的 i18n 键纳入装配脚本（防 MXU 更新覆盖 locales 后再丢）

#### 提交

`43a7be738`（节点化）→ `04fb42ec8`（改普通任务）→ `460485529`（import 过滤）→ `777634643`（i18n）

### 2026-10-23 14:5x · 启动网页端最终定性：退回 preAction（`b7a116a42`）

#### 实测结论：`StartApp` 在 Linux 控制器上不可用

| 参数写法 | 结果 |
|---|---|
| `{"command": "/root/maaend/web/linux/wsl/start_sway.sh"}` | `Node.Action.Failed`，4.0s |
| `{"path": "/root/maaend/web/linux/wsl/start_sway.sh"}` | `Node.Action.Failed`，4.0s |

任务链本身是通的（任务名解析、节点链接、i18n、预设排序全对），失败只发生在动作层：

```text
--- (1/1) WebLaunchBrowser -> WebLaunchSwayStart
action [i=0] result={"action":"StartApp", ...}  → Node.Action.Failed
=> done=True succeeded=False 4.0s    （重试一次，同样 4.0s）
```text

`StartApp` 在 MaaFw 里是 ADB 语义（`package/activity`），Linux/Wayland 控制器未实现；
go-service 的 85 个自定义动作里也没有“执行外部命令”这类动作。

#### 因此的最终形态

- **启动**：预设 preAction `▶️ 启动网页端（sway + Chrome，无头）` → `start_web.sh`（通过 `program: /bin/bash` + `args`，由 MXU 直接 exec，绕过 pipeline）
- **进游戏**：任务 `WebStartGame` → `WebStartGameEntry` → base 登录链 → 大世界
- 删除：`web/tasks/WebLaunchBrowser.json`、对应 import（72→71）、5 个 StartApp 节点（35→30）

#### 若将来要把“启动”搬回任务体系

唯一可行路径是**自定义 agent**：用一个极小的 agent 注册 `LaunchWebClient` 动作（exec 脚本），
pipeline 写 `action: Custom, custom_action: LaunchWebClient`，并接到 MXU 的 `child_exec`。
不要在 `StartApp` 上再花时间。

### 2026-10-23 15:4x · 云串流取图链路实测 + 原生帧方案立项

#### 图像从哪来（实测）
```text
串流 1920x1080 @60fps → CSS 2561x1440（浏览器放大 1.33x）→ sway 合成 2560x1440
→ wlr-screencopy → MaaFw 默认缩到 1280x720
```text
`<video>` 元素可直接抠出原生帧：`wsl_raw.png` 1920x1080（1.5–2.4 MB PNG），无浏览器 UI。

#### 抓帧分辨率可调，但被上游锁在 720p
控制器支持 `set_screenshot_target_long_side(1920/2560)`、`set_screenshot_use_raw_size(True)`，实测四档均生效。
但上游 `resource` 5997 节点中 650 个带框模板全在 1280x720 空间（最大右边界 1287 / 下边界 800），
MaaFw 不做模板缩放 → 改抓帧分辨率会让 650 个模板全部失效，且每次上游更新覆盖回来。

#### 同屏实测（静止画面，两次 720p 抓帧平均像素差 0.98）
| 来源 | 720p 锐度 | 相对现状 |
|---|---|---|
| 现有链路 1080→1440→720 | 501.1 | 基准 |
| 原生 1080 + LANCZOS | 651.3 | +30% |
| 原生 1080 + AREA/BOX | 640.7 | +28% |
| 原生 1080 + BICUBIC | 534.0 | +7% |
| 原生 1080 + BILINEAR | 353.2 | −30% |

结论：**缩放算法比来源更关键**；「舞台降到 720p 让 Chrome 下采样」有变糊风险（Chrome 视频缩放接近 bilinear）。

#### 立项
写 `CdpController`（`maa.controller.CustomController`）：screencap 从 `<video>` 抠原生帧 → AREA 降到 720p，
输入走 CDP `Input.dispatchMouseEvent` / `dispatchKeyEvent`。设计、风险、验收标准见
`web/docs/cdp-native-capture.md`。

### 2026-10-23 15:5x · CdpController 落地（`d11036679`）

从云串流 `<video>` 取原生帧，绕开「1080→1440→720」两次重采样。

验收（WSL 实测）：
| 项 | 结果 |
|---|---|
| 抓帧 | 1280x720，锐度 1174（现有链路 501，+134%） |
| 延迟 | 后台 ~190ms/帧，screencap 命中缓存 0–7ms |
| 鼠标 | 点 (1252,30) → CSS (1669.7,40.0)，Esc 菜单关闭回大世界 |
| 键盘 | `key_down/key_up(27)` 打开 Esc 菜单 |
| 任务 | `--controller cdp --tasks WebStartGame` → OK 1.0s |

同时修 `resolve_preset.ROOT` 默认回落到 Windows 安装目录的问题（导致直跑时
自有任务被判「未知任务」）。归档副本在 `archive_wsl_20261023/`，tag `web-cdp-20261023`。

### 2026-10-23 16:5x · CDP 控制器设为默认 + 三个真 bug

`--controller` 默认值从 `wlroots` 改为 `cdp`（`MAAEND_CONTROLLER=wlroots` 可退回），
并加**显式回退**：CDP 连不上时日志打印 `[!] CDP 控制器连接失败，回退到 wlroots`，不静默降级。

#### 修掉的三处（都是实测踩出来的）

1. **灰度匹配分数不够** —— `WebLauncherStartButton` 模板是从合成器帧抠的，
   在 `Page.captureScreenshot` 帧上 RGB NCC 0.9919，但 MaaFw 用**灰度**匹配只有 **0.9013**
   （阈值 0.95），日志里 0.9160 反复失败。→ 新增 `web/linux/resource_web_cdp/image/WebStartGame/StartButton.png`，
   只在 `--controller cdp` 时作为最后一层追加（homesrv 合成器路径不受影响）。改后分数 **1.000000**。

2. **无 video 时点击坐标没有缩放** —— 坐标换算原来只认 `<video>` 的 rect；启动页没有 video，
   于是 1280x720 的点击坐标被当成 CSS 坐标直接派发（CSS 视口是 1707x960，差 1.33 倍），
   表现为「Click 成功但游戏不启动」。→ `_refresh_rect()` 在无 video 时回落到 `window.innerWidth/Height`。
   改后点 (1017,540) → CSS (1356.3,720)，云会话正常拉起（video 1920x1080）。

3. **标题页「点击任意位置继续」没有任何节点覆盖** —— 原 `__ScenePrivateCloudClickToContinue`
   期望的是「点击屏幕继续」且 ROI 在底部中间 `[440,630,400,90]`，
   而游戏标题页写的是「点击任意位置继续」，位置在右中 `≈(1205,380)`。→ 新增
   `WebTitleClickToContinue`（OCR，ROI `[300,300,980,420]`）+ `WebWaitInGame`（轮询等待加载，
   timeout 180s），插到 `WebStartGameEntry` / `WebLauncherStartButton` 的 next 首位。

#### 验证（默认控制器，无 `--controller` 参数）

- 启动器 `开始游戏` 命中 1.000000 → Click 生效 → 云会话拉起（video 1920x1080）
- 标题页 OCR 命中 → 点击 → 进入 NOW LOADING 界面
- 加载完成后 `WebAlreadyInGame` 命中 → `WebStartGame OK 1.0s`，`通过 1 / 1`
