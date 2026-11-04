# AutoEssence 0/8：静态已证与待实机复验

## 0. 结论摘要

| # | 结论 | 分级 | 对 0/8 的作用 |
| --- | --- | --- | --- |
| 1 | 云层缺官方 `AutoEssence/CommonNodes/Capacity.json` 的两个节点（`AutoEssenceCapacityClickSave` 覆盖 + `AutoEssenceCapacitySaveClosed` 新增） | `static`（基线 `b8cda0c66`） | **代码级确定缺陷**：容量判定必误读，每轮产出 0 或直接任务失败 |
| 2 | `GotoTriggerPointMove_VFTheHub` 的 `MapNavigateAction` 两轮共失败 7 次，单次 81.8s / 85.9s，窗口内 74.6s / 82.3s 完全没有事件 | `log`（旧部署） | 可能是 0/8 的当轮直接原因，但**日志早于重构版部署，需复验** |
| 3 | `GotoTriggerPointMaybeTeleport_VFTheHub` 的 `max_hit: 3` 被前两次失败吃光，之后 `[Anchor]` 重试每 1s 空转一次、共 21 次，最后以 20s `reco_timeout` 收尾 | `static` + `log` | 放大器：把一次导航失败放大成 190–206s 的整轮失败，并把失败归因到错误的节点名 |
| 4 | `essence.log` 不含任何 cpp-algo 内部行，导航失败原因不可见 | `static`（可观测性） | 不是失败原因，但让 2 无法定论 |

**修 1 不会让 2 消失；修 2 也不会让 1 消失。** 1 是确定要补的数据层缺陷，2 需要用重构版实机复验。

## 1. 时间线纠正（先读）

夜间链 `11-04 03:00–04:22`（`daily rc=7` / `essence rc=7`）跑的是**部署前**的旧 `web/linux`；
重构版 `11-04 15:05` 才部署（备份 `~/maaend/web/linux.bak-20261104-1505`），15:10 单跑 `WebStartGame`
成功 61.0s。

所以夜间日志里的 `invalid node id`（`AutoEssenceConfirmObtain` 03:53、`WebStartGameEntry` 04:03、
`WebCloseRewards` 04:04）**不能当作当前代码的失败证据**：部署态 `~/maaend/resource/pipeline/` 只有合并的
`nodes.json`，`WebStartGameEntry` 等节点在覆盖层 `web/resource_web/pipeline/nodes.json` 里，那一轮没加载到
覆盖层目录，属旧部署/环境问题。

脚本用 `freshness.log_precedes_code` 自动判这条：本次样本日志末条 `2026-11-04 04:22:29.330`，
代码 mtime `2026-11-04T15:58:51` → `E-STALE-LOG`，所有日志结论降级为 `warn`。

## 2. 静态已证：云层缺官方容量门控（`static`）

### 2.1 官方这两个节点

`D:\maaend-official\assets\resource_cloud\pipeline\AutoEssence\CommonNodes\Capacity.json`（31 行，2 节点）：

- 第 2–3 行注释写明用途：「云端画面有延迟：点保存后头几帧仍是筛选弹窗，底栏静止就放行，
  会隔着弹窗读到「已选择 0/200」。先确认弹窗已关、回到回收页（底部提示语被弹窗遮住时不会命中），
  再读已选择数量。」
- 第 4–8 行 `AutoEssenceCapacityClickSave`：只做 `next` 覆盖 → `["AutoEssenceCapacitySaveClosed"]`。
- 第 9–30 行 `AutoEssenceCapacitySaveClosed`：`recognition = And(all_of: [AutoEssenceCapacityDecomposePrompt])`
  （回收页「无法分解」提示重新出现 = 筛选弹窗已关），`next = [BatchReady, CannotReach, NothingLeft]`。

### 2.2 我们的链走到哪一步依赖它

`assets/resource/pipeline/AutoEssence/CommonNodes/Capacity.json`（base，上游文件）：

- `AutoEssenceCapacityClickSave` 定义在 **742** 行，`post_wait_freezes` 只等底栏 `[0,620,250,80]`
  （**763–772** 行，`timeout: 1000`），`next` 直接是三个判定节点（**775–779** 行）。
- 三个判定节点都是对 `{AutoEssenceCapacitySelectedCountOCR}` 的表达式：
  `BatchReady` **804** 行（`0 < 已选择`）、`CannotReach` **822** 行（`已选择 == 0 && 1800 < 总库存`）、
  `NothingLeft` **840** 行（`已选择 == 0 && 总库存 <= 1800`）。
- `AutoEssenceCapacitySelectedCountOCR` **781** 行，ROI `[0,620,220,70]`（**787–792** 行）——
  正是被筛选弹窗盖住的那块底栏。
- 误判后的去向：`CannotReach` → `AutoEssenceCapacityAbortExit`（**837** → **1051** 行）→
  `AutoEssenceCapacitySelectFailed`（**1078** 行，`focus` 用 `$task.DecomposeWeaponEssence.focus.insufficient`，
  即**任务失败**）；`NothingLeft` → `AutoEssenceCapacityClickExit`（**855** → **1024** 行）→ 退出分解页，
  **本轮不分解、产出 0**。

也就是说：云上「点保存 → 立刻读底栏」这条路径，只要弹窗晚关几帧，就会稳定落到 `CannotReach`（任务失败）
或 `NothingLeft`（空跑一轮）。这与「8 轮全不成功」的现象一致。

### 2.3 基线证据（`b8cda0c66`）

基线云层只有 13 个文件，没有 `AutoEssence/` 目录：

```text
git ls-tree -r --name-only b8cda0c66 -- assets/resource_cloud_adb/pipeline
# 13 个文件：AutoStockStaple / Common / CreditShopping / DailyRewards / DijiangRewards /
#            OutpostTrading / SceneManager / SeizeDeliveryJobs / VisitFriends
```

脚本以 `--root <b8cda0c66 的 resource_cloud_adb 快照>` 跑出的差集：

```text
云层差集 : 仅官方有的文件 5 个 / 节点 10 个
  AutoEssence 子树缺: ['AutoEssenceCapacityClickSave', 'AutoEssenceCapacitySaveClosed']
退出码   : 2
```

完整快照见 [cloud-layer-diff-baseline.json](cloud-layer-diff-baseline.json)。

### 2.4 当前状态（迁移后已修）

资源层重组（`11-04 15:46`，见 `docs/project-20261104/PLAN.md` §7）已把官方文件原样抄入：

- `assets/resource_cloud/pipeline/AutoEssence/CommonNodes/Capacity.json` 与官方**逐字节相同**（997 字节，`bytes` 比对通过），`ClickSave.next = ["AutoEssenceCapacitySaveClosed"]`。
- 我们自己的两个网页补丁节点（`AutoEssenceCapacitySwitchToWeaponTab`、`AutoEssenceCapacityCursorPark`）
  单独放在 `assets/resource_cloud_web/pipeline/AutoEssence/CommonNodes/Capacity.json`，**不覆盖**门控节点。

脚本在当前树上复跑：`仅官方有的文件 0 个 / 节点 0 个`，`必补节点缺: 无`，无跨层冲突。

⚠️ 迁移期唯一要防的回归：**同名节点被深层整份覆盖**。若哪天 `resource_cloud_web` 也定义
`AutoEssenceCapacityClickSave` 且 `next` 是三个判定节点，门控会被静默盖掉；脚本用
`E-GATE-OVERRIDDEN` 专门盯这一条（`diagnose_essence.py` 的 `gate_override_conflicts`）。

## 3. 待实机复验：走位失败（`log`，旧部署）

样本 `essence-sample.txt`（第 5、6 轮）：

| 轮 | 走位尝试 | 窗口 | 用时 | 窗口内最大静默 | 窗口内 MapNavigator 子任务 |
| --- | --- | --- | --- | --- | --- |
| 5 | 1 | 04:16:07.346 → 04:17:29.147 | 81.8s | 74.6s（04:16:14.524 → 04:17:29.147） | InteractStart/End、ObstacleDevice 全链（含 CloseUnknownDeviceDialog） |
| 5 | 2 | 04:17:39.709 → 04:18:18.729 | 39.0s | 38.4s | InteractStart/End |
| 5 | 3 | 04:18:18.729 → 04:18:38.735 | 20.0s | 20.0s | 无（anchor 空转 21 次） |
| 6 | 1 | 04:19:18.211 → 04:20:44.130 | 85.9s | 82.3s | InteractStart/End |
| 6 | 2 | 04:20:56.202 → 04:21:40.096 | 43.9s | 36.9s | InteractStart/End、ObstacleDevice + NoHit |
| 6 | 3 | 04:21:53.074 → 04:22:09.323 | 16.2s | 14.4s | InteractStart/End |
| 6 | 4 | 04:22:09.323 → 04:22:29.330 | 20.0s | 20.0s | 无（anchor 空转 21 次） |

两轮、六次真实导航尝试**全部**在 16–86s 内失败，且每次都以 `MapNavigatorInteractStart → InteractEnd`
开场，随后长时间完全没有事件。机制候选与所需证据见
[navigate-trigger-point.md](navigate-trigger-point.md)。

日志原文（`essence.log`）：

```text
[2026-11-04 04:16:07.547][WRN][Actuator.cpp][L715] custom action target rect is empty,
  continue with empty rect [name=GotoTriggerPointMove_VFTheHub] [param.name=MapNavigateAction]
[2026-11-04 04:17:29.147][INF][EventDispatcher.hpp] [msg=Node.PipelineNode.Failed]
  [details={... "name":"GotoTriggerPointMove_VFTheHub","success":false}]
[2026-11-04 04:17:29.147][WRN][PipelineTask.cpp][L71] node not completed, handle error
  [node.name=GotoTriggerPointMove_VFTheHub]
```

`custom action target rect is empty` 对 `DirectHit` 节点是**常态**（同一句在 04:17:39 又出现一次，
而那次节点是成功的），不是失败原因，不要被它带偏。

## 4. 放大器：`max_hit` 用尽后的 20s 盲转

- `assets/resource/pipeline/AutoEssence/RegionNodes/VFTheHub.json` **16** 行：`"max_hit": 3`。
- 同文件 **74–76** 行：`GotoTriggerPointMove_VFTheHub.on_error = ["[Anchor]AutoEssenceMoveToTriggerPointMaybeTeleport"]`。
  Anchor 映射在 **5–8** 行（`AutoEssenceMoveToTriggerPointMaybeTeleport → GotoTriggerPointMaybeTeleport_VFTheHub`）。
- `GotoTriggerPointMaybeTeleport_VFTheHub` 的 `next` 又是 `GotoTriggerPointMove_VFTheHub`（**28–30** 行）——
  失败 → 传送 → 再走 → 再失败，直到 `max_hit` 用尽。
- 用尽后 anchor 解析立刻返回失败（每 1s 一次，21 次），外层 `reco_timeout=20000ms` 到点：

```text
[2026-11-04 04:18:38.735][WRN][PipelineTask.cpp][L155] Task timeout
  [pretask.name=GotoTriggerPointMove_VFTheHub] [duration_since(start_clock)=20005ms] [pretask.reco_timeout=20000ms]
[2026-11-04 04:18:38.735][WRN][PipelineTask.cpp][L245] PipelineTask bad next
```

后果：`Tasker.Task.Failed` + `[04:18:39] AutoEssence FAIL 192.1s` / `[04:22:29] AutoEssence FAIL 206.1s`。
排查时容易被 `Task timeout [pretask.name=GotoTriggerPointMove_VFTheHub]` 误导成「走位节点自身超时」，
实际是**它失败之后的重试链超时**。

## 5. 可观测性缺口（`static`）

`essence.log` 由 `lib.sh:247` 的 `exec >>"$LOG" 2>&1`（`essence_run_homesrv.sh:26` 调 `mh_init`）
收集 maafw 输出，但 **cpp-algo 的日志不在这条流里**：`agent/cpp-algo/source/main.cpp` **73–74** 行把
`MaaGlobalOption_LogDir` 指到 `debug/cpp-algo/debug`（`kLogDir` 定义在 **32** 行）。本机核验：

```text
grep -c "PositionProvider\|NavigationStateMachine" ~/maaend/essence.log   # → 0
```

所以 74.6s 内导航器在等什么，只能从 `~/maaend/debug/cpp-algo/debug/` 取；`diagnose_navigate.py`
会检查该目录并在缺失时报 `N-NO-CPP-LOG`。

## 6. 最小复验步骤（部署后，单任务 + 抓帧）

```bash
# 0) 只跑一轮基质（不跑整夜）：默认 TARGET_OK=4 / MAX_ATTEMPTS=6
#    （essence_run_homesrv.sh:22-23），这里压成 1 轮、失败也不重试
cd ~/maaend
MAAEND_ESSENCE_OK=1 MAAEND_ESSENCE_MAX=1 MAAEND_ESSENCE_SLEEP=0   bash web/linux/homesrv/essence_run_homesrv.sh
#    跑完看 : tail -n 40 ~/maaend/essence.log
#    日志路径由 lib.sh:247 的 exec >>"$LOG" 2>&1 决定，LOG=~/maaend/essence.log

# 0.5) 先确认「仓库里的门控」在部署机上真的会被加载
#      lib.sh:110-127 的层序：resource → resource_cloud → resource_cloud_web → web/linux/resource_web_linux
#      注意 resource_cloud_web 存在时，web/resource_web 与 web/resource_web_homesrv 不再加载
ls -d ~/maaend/resource ~/maaend/resource_cloud ~/maaend/resource_cloud_web 2>&1
ls ~/maaend/resource_cloud/pipeline/AutoEssence/CommonNodes/Capacity.json 2>&1
grep -c "AutoEssenceCapacitySaveClosed"     ~/maaend/resource_cloud/pipeline/AutoEssence/CommonNodes/Capacity.json

# 1) 跑完立刻离线判读（不需要游戏在跑）
python3 web/linux/homesrv/diagnose_essence.py \
    --log ~/maaend/essence.log --root ~/maaend --repo ~/maaend \
    --official ~/maaend-official --json-out /tmp/diag-essence.json

# 2) 只看走位窗口
python3 web/linux/homesrv/diagnose_navigate.py \
    --log ~/maaend/essence.log --root ~/maaend --repo ~/maaend \
    --node GotoTriggerPointMove_VFTheHub --json-out /tmp/diag-nav.json

# 3) 若失败点仍是 GotoTriggerPoint*，取 cpp-algo 内部日志一起看
ls -la ~/maaend/debug/cpp-algo/debug/ | tail
```

判定标准：

- `deploy_layers.effective` 含 `resource_cloud`，且 `required_nodes.AutoEssenceCapacityClickSave.winner.layer`
  是云层而不是 `resource`——否则门控没生效（`E-DEPLOY-GATE-ABSENT` / `E-DEPLOY-GATE-NEUTRALIZED`）。
- `chain.reached.capacity == true` 且 `capacity_verdict_hits` 出现 `BatchReady` → 门控按预期工作；
  出现 `NothingLeft`/`CannotReach` 而「已选择」应大于 0 → 门控没生效（回头看 2.4 的覆盖风险）。
- `chain.nav_windows` 里 `Failed` 的 `global_max_gap_s` 仍 ≥ 20s → 走位问题与旧日志同型，按
  `navigate-trigger-point.md` 继续取 cpp-algo 日志。
- `freshness.log_precedes_code == false` 才算「当前代码的观测」。
