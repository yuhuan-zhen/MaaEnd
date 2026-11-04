# 走位失败：`GotoTriggerPointMove_*` 窗口与机制候选

> 数据来源：`essence-sample.txt`（2026-11-04 04:15–04:22 夜间链，**部署前**的旧 `web/linux`）。
> 结论一律标 `log`，复验前不得当作重构版代码的缺陷。静态项单列。

## 1. 一句话

`MapNavigateAction` 每次启动后都先跑一轮 `MapNavigatorInteractStart → MapNavigatorInteractEnd`（交互提示扫描，
OCR 返回空），随后 16–86s 内**完全没有事件**，最后 `Node.PipelineNode.Failed`；
两轮共 7 次失败，波形一致——不是偶发。

## 2. 窗口（`diagnose_navigate.py --node GotoTriggerPointMove_VFTheHub`）

| 轮 | 尝试 | 起点（上一事件） | 终点 | 用时 | 窗口内最大静默 | 窗口内 MapNavigator 子任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 1 | 04:16:07.346 MaybeTeleport Succeeded | 04:17:29.147 Failed | 81.8s | 74.6s（04:16:14.524 → 04:17:29.147） | InteractStart/End、ObstacleDevice 全链 |
| 5 | 2 | 04:17:39.709 MaybeTeleport Succeeded | 04:18:18.729 Failed | 39.0s | 38.4s | InteractStart/End |
| 5 | 3 | 04:18:18.729 Failed | 04:18:38.735 Failed | 20.0s | 20.0s | 无（anchor 空转 21 次） |
| 6 | 1 | 04:19:18.211 MaybeTeleport Succeeded | 04:20:44.130 Failed | 85.9s | 82.3s | InteractStart/End |
| 6 | 2 | 04:20:56.202 MaybeTeleport Succeeded | 04:21:40.096 Failed | 43.9s | 36.9s | InteractStart/End、ObstacleDevice + `_NoHit` |
| 6 | 3 | 04:21:53.074 MaybeTeleport Succeeded | 04:22:09.323 Failed | 16.2s | 14.4s | InteractStart/End |
| 6 | 4 | 04:22:09.323 Failed | 04:22:29.330 Failed | 20.0s | 20.0s | 无（anchor 空转 21 次） |

「静默」= 全时间线（不分 task）上两个相邻 `Node.*` 事件的最大间隔。之所以要跨 task 统计：
cpp-algo 的每个子任务各占一个 `task_id`（`MapNavigatorInteractStart` 是 `200000022`、
`MapNavigatorObstacleDevice` 是 `200000023`），而 AutoEssence 主链是 `200000005`，
按 task 分组会把「换 task 后彻底没动静」漏掉。

## 3. 日志原文（关键 6 行）

```text
[2026-11-04 04:16:07.547][WRN][Actuator.cpp][L715] custom action target rect is empty,
  continue with empty rect [name=GotoTriggerPointMove_VFTheHub] [param.name=MapNavigateAction]

[2026-11-04 04:16:07.938][INF] [msg=Node.PipelineNode.Succeeded]
  name=MapNavigatorInteractStart   (task 200000022)
[2026-11-04 04:16:08.017][WRN][OCRer.cpp][L174] Wrong ocr_result size [boxes=[]] [texts=[""]] [scores=[0.000000]]
[2026-11-04 04:16:08.017][INF] [msg=Node.PipelineNode.Succeeded] name=MapNavigatorInteractEnd

[2026-11-04 04:16:11.657][INF] name=__MapNavigatorObstacleDevice_WaitFreezes  box=[845,507,20,20] score=0.923774
[2026-11-04 04:16:12.077][INF] name=__MapNavigatorObstacleDevice_InteractPre     KeyDown keycode=[18]
[2026-11-04 04:16:12.529][INF] name=__MapNavigatorObstacleDevice_Interact        Click point=[862,512]
[2026-11-04 04:16:14.524][INF] name=__MapNavigatorObstacleDevice_CloseUnknownDeviceDialog Click [1104,130]

[2026-11-04 04:17:29.147][INF] [msg=Node.PipelineNode.Failed]
  [details={... "name":"GotoTriggerPointMove_VFTheHub","success":false}]
[2026-11-04 04:17:29.147][WRN][PipelineTask.cpp][L71] node not completed, handle error
  [node.name=GotoTriggerPointMove_VFTheHub]
```

`custom action target rect is empty` 是 `DirectHit` 节点的常态告警（04:17:39 又出现一次，而那次节点是成功的），
**不是**失败原因。

## 4. 静态前置条件（都已核对）

| 项 | 结果 | 依据 |
| --- | --- | --- |
| navmesh 数据在 | ✅ `assets/resource/model/map/navmesh/base.nav.gz`（98 MB） | `navi_config.h:461-462` 的默认相对路径 |
| 路线声明的 zone 在 navmesh 里 | ✅ `ValleyIV_Base` 命中（扫描前 64 MB） | `VFTheHub.json:44` |
| 路线引用的 interact 节点已定义 | ✅ `__AutoEssenceRecoApproachInteractText` / `...Scan` | `CommonNodes/Recognition.json:140` / `:173` |
| 源码转向系数 | `kTurn360UnitsPerWidth = 1.0856`（3.86 units/度） | `navi_config.h:24` |
| 部署二进制是否为该版 | ⚠️ 需在 homesrv 上核对 md5 `4056272952b61fe10a9e0a0e7484bbf5` | `homesrv/auto_update.sh:223`（`WANT_MD5`） |
| cpp-algo 内部日志 | ❌ 本机无 `debug/cpp-algo/debug`；`essence.log` 0 条 cpp-algo 行 | `main.cpp:32`、`:73-74` |

## 5. 机制候选（按可能性排序，均需 cpp-algo 日志定论）

### 候选 A：唯一的设备恢复被「目的地激发点」吃掉（中）

- `kRecoveryDeviceAttempts = 1`（`navi_config.h:560`）——设备恢复整条链只准试 1 次。
- 探针模板是通用交互图标 `resource/image/MapNavigator/ObstacleDevice/InteractButton.png`，
  门槛只有 0.65（`navi_config.h:551-552`）；样本里 0.9238 命中于屏幕正中 `[845,507]`。
- 传送锚点在 `(452.4, 910.3)`，路线 NAVMESH 目标 `(456.92, 932.86)`，终点 INTERACT `(463.41, 938.85)`
  （`VFTheHub.json:46-65`）——锚点旁边就是激发点本体，角色一落地正前方就是它的交互提示。
- 于是第 1 次（也是唯一一次）设备恢复被用于「点掉」这个设备：04:16:12 点击、04:16:14 关掉
  「未知设备」对话框，之后 74.6s 没有任何子任务——恢复阶梯已经没有设备这一档可用。
- 反向证据：`interact_rec: true`（`VFTheHub.json:64`）本意是「导航只到点不按键，把按哪一行交回外层」，
  所以导航**不应该**去按这个设备；它按了，说明目的地提示被当成了障碍。

**确认方式**：cpp-algo 日志里 `ObstacleDeviceRecovery` / `NavigationStateMachine` 的 reason；
或 `--probe` 时 `__MapNavigatorObstacleDevice_InteractPre` 在「已到激发点」画面上仍命中。

### 候选 B：定位在云串流下反复丢失 → 走廊零进展（中）

- `kLocalizationLossTimeoutMs = 30000`（`navi_config.h:240` → `:205`），超时才 fail（`navigation_state_machine.cpp:649`）；
  期间每次全局重定位成功都会 `loss.Reset()`，所以在「时好时坏」的云画面上总时长可以远超 30s。
- 与观测吻合：窗口 74.6–82.3s 无事件（不是「有事件但都失败」），符合「一直在等定位、没有可派发的子任务」。
- 不吻合处：定位彻底失败时通常仍会周期性派发 `MapNavigatorInteractStart`/截图，而样本里静默是**零事件**。

**确认方式**：cpp-algo 日志中 `PositionProvider::Capture` 的命中率与 `localization_lost_timeout` reason；
`--probe` 对 `InMapValleyIVTheHub` 打分（借 homesrv `map_probe.py` 的同一套只读识别）。

### 候选 C：输入后端（转向/前进）没生效（低）

- 点击类输入是有效的（04:16:14 关闭对话框模板 0.974，说明按键/点击确实进了游戏），所以不是全局输入失效。
- 但转向系数/拖拽映射若错（部署到非 1.0856 版），会表现为「一直在转、走廊不前进」，同样以 stall 收场。
- 本机无法判定，必须核对部署二进制 md5（见第 4 节）。

### 候选 D：路线本身与云版地图不一致（低）

`ValleyIV_Base` 的模板尺度是特例（`MapTypes.h:226` 的 `15.0/16.0`）；若部署的地图底图与 navmesh
不是同一次烘焙，`ZONE ValleyIV_Base` 的确认会一直不过（`kZoneConfirmTimeoutMs = 12000`，`navi_config.h:325`）。
12s 与观测的 16–86s 不吻合，故排后。

## 6. 下一步（按顺序，全部只读）

```bash
# a) 先补可见性：把 cpp-algo 日志目录找出来（应为 ~/maaend/debug/cpp-algo/debug）
python3 web/linux/homesrv/diagnose_navigate.py --log ~/maaend/essence.log \
    --root ~/maaend --repo ~/maaend --json-out /tmp/nav.json
python3 -c "import json;d=json.load(open('/tmp/nav.json'));print(d['static']['cpp_algo_logs'])"

# b) 核对部署二进制版本（不匹配 = 先换回 1.0856 再谈导航）
md5sum ~/maaend/agent/cpp-algo   # 期望 4056272952b61fe10a9e0a0e7484bbf5

# c) 复现时抓一次只读帧评分（不点击）：确认「已到激发点」画面上交互提示是否命中
python3 web/linux/homesrv/diagnose_navigate.py --log ~/maaend/essence.log \
    --root ~/maaend --probe --sock /run/user/1000/wayland-1

# d) 拿到 cpp-algo 日志后，直接搜失败原因字符串
grep -nE "FailNavigation|localization_lost|localization_thrash|offroute|stall|ObstacleDevice" \
    ~/maaend/debug/cpp-algo/debug/*.log | tail -40
```
