# 云层与官方 `resource_cloud` 的节点差集

对比对象：

- 官方：`D:\maaend-official\assets\resource_cloud\pipeline\`（commit `ba5887d64` = `upstream/v2`，**14 个文件 / 27 节点**）
- 我们（基线 `b8cda0c66`）：`assets/resource_cloud_adb/pipeline\`（**13 个文件**，无 `AutoEssence/`）
- 我们（当前）：`assets/resource_cloud\pipeline\` + `assets/resource_cloud_web\pipeline\`

复现命令：

```bash
python3 web/linux/homesrv/diagnose_essence.py --log ~/maaend/essence.log \
    --root <树根> --repo <树根> --official ~/maaend-official
```

## 1. 文件级差集（基线）

仅官方有的 5 个文件：

| 文件 | 节点 | 是否落在 AutoEssence 链上 |
| --- | --- | --- |
| `AutoEssence/CommonNodes/Capacity.json` | 2 | **是**（见 [autoessence-0of8.md](autoessence-0of8.md)） |
| `AutoSell/Recognition.json` | 2 | 否（AutoSell 好友报价） |
| `GiftOperator/GiftOperatorContact.json` | 3 | 否（送礼） |
| `GiftOperator/GiftOperatorGiftFlow.json` | 1 | 否（送礼） |
| `Interface/InScene/EnvironmentMonitoring.json` | 2 | 否（环境监测/采集） |

合计 **10 个节点**（脚本 `node_only_official`）。

「否」不等于「可以不管」：这些节点名在 base（`assets/resource/pipeline/**`）里都有同名定义，
官方云层只是**覆盖阈值/ROI/颜色范围**。缺覆盖 = 退回 PC 版判定，云串流的压缩与延迟下同样可能失配；
本次只确认它们不在这条基质链上。

## 2. 节点级明细

| 节点 | 官方文件 | base 里的同名定义 | 缺了会怎样 |
| --- | --- | --- | --- |
| `AutoEssenceCapacityClickSave` | `AutoEssence/CommonNodes/Capacity.json:4-8` | `AutoEssence/CommonNodes/Capacity.json:742` | `next` 直连三个判定节点，隔着筛选弹窗读「已选择 0/200」→ `CannotReach`/`NothingLeft` |
| `AutoEssenceCapacitySaveClosed` | `AutoEssence/CommonNodes/Capacity.json:9-30` | 无（官方新增） | 没有「等弹窗关掉」这一步，上面的误读无法避免 |
| `AutoSellFriendsPriceCurrentAreaRecognition` | `AutoSell/Recognition.json` | `AutoSell/Recognition.json` | AutoSell 区域价判定退回 PC 版 |
| `AutoSellFriendsPricesExpectedGoToHighlightRecognition` | `AutoSell/Recognition.json` | `AutoSell/Recognition.json` | 同上（高亮行判定） |
| `EnvironmentMonitoringMarkerStoneMonitoringTerminalSelected` | `Interface/InScene/EnvironmentMonitoring.json` | `Interface/InScene/Region.json` | 环境监测终端「已选中」判定退回 PC 版 |
| `EnvironmentMonitoringOutskirtsMonitoringTerminalSelected` | `Interface/InScene/EnvironmentMonitoring.json` | `Interface/InScene/Region.json` | 同上（郊外终端） |
| `GiftOperatorCheckSelectedLabelColor` | `GiftOperator/GiftOperatorContact.json` | 同名 | 送礼选中态判定退回 PC 版 |
| `GiftOperatorCheckSelectedTextColor` | `GiftOperator/GiftOperatorContact.json` | 同名 | 同上 |
| `GiftOperatorNotSelect` | `GiftOperator/GiftOperatorContact.json` | 同名 | 同上 |
| `GiftOperatorClickGiftColor` | `GiftOperator/GiftOperatorGiftFlow.json` | 同名 | 送礼入口颜色判定退回 PC 版 |

## 3. 字段级差异（基线）

| 文件 | 节点 | 官方 | 我们（基线） | 影响 |
| --- | --- | --- | --- | --- |
| `Common/Button/ButtonColor.json` | `WhiteButtonBackground` | `lower[0] = [253,251,251]` | `lower[0] = [255,253,253]` | 我们把纯白卡死在 255，云串流把纯白压到 253 时白色按钮背景**不命中**；`WhiteCancelButton.json:10`、`WhiteConfirmButtonType1.json:39` 等以它为 ROI/判据 |

其余同文件逐键相同（`AutoStockStaple/General/Item.json`、`Common/Private/AutoUseSpMedication/Recognition.json`、
`CreditShopping/Item.json`、`DailyRewards/Event.json`、`DailyRewards/Event/TitleYellow.json`、
`OutpostTrading/SellCore.json`、`VisitFriends/MenuScan.json`）。

`SceneManager/SceneLogin.json`：我们比官方**多**一个 `__ScenePrivateLoginCloseDialog`（登录弹窗关闭），
属我们自己的云版修复，保留。

## 4. 我们多出的 4 个文件（官方没有）

`DijiangRewards/GrowthChamber.json`、`DijiangRewards/MainFlow.json`、`SceneManager/SceneCommon.json`、
`SeizeDeliveryJobs/SeizeDeliveryJobsEndpointFilter.json`。

判断：都是网页端特有的界面差异修复，官方云层没有对应物属正常。迁移时**不要**顺手删。

## 5. 迁移后状态（当前树）

| 项 | 基线 `b8cda0c66` | 当前 |
| --- | --- | --- |
| 仅官方有的文件 | 5 | **0** |
| 仅官方有的节点 | 10 | **0** |
| 门控节点所在层 | 无 | `resource_cloud`（`AutoEssenceCapacityClickSave` / `AutoEssenceCapacitySaveClosed`） |
| 门控是否被深层覆盖 | — | 否（`resource_cloud_web` 只放 `SwitchToWeaponTab` / `CursorPark` 两个自有节点） |
| `ButtonColor.json` 字段差异 | 1 节点 | 已与官方逐字节相同 |

`assets/resource_cloud/pipeline/AutoEssence/CommonNodes/Capacity.json` 与官方 **997 字节逐字节相同**。

## 6. 需要继续盯的三件事

1. **深层整份覆盖**：`resource_cloud_web` 若将来也定义 `AutoEssenceCapacityClickSave`，会把云层门控整份盖掉
   （deep merge 是「整节点替换」，不是字段合并）。脚本用 `E-GATE-OVERRIDDEN` / `cross_layer_conflicts` 盯这条，
   并按部署层序解析「谁真正生效」（`E-DEPLOY-GATE-NEUTRALIZED`）。

2. **部署层序本身也会吞掉修复**（`homesrv/lib.sh:110-127` 的 `mh_res_dirs`）：

   - 层序 `resource → resource_cloud → resource_cloud_web → web/linux/resource_web_linux`；
   - `resource_cloud` 是「官方云层，新版本才发」，缺失时 `|| true` 静默跳过 —— 老发行版上**门控根本不会加载**；
   - `resource_cloud_web` 一旦存在，`web/resource_web` 与 `web/resource_web_homesrv` **不再加载**（仅兜底），
     这正是旧部署里 `WebStartGameEntry`/`WebCloseRewards` 报 `invalid node id` 的机制；
   - 所以「仓库里有」≠「线上生效」，复验第一步要 `ls ~/maaend/resource_cloud ...` 并看脚本的
     `deploy_layers.effective`。

3. **`ButtonColor.json` 的白色下限**：已随迁移对齐官方；若后续有人本地「修」回去（255），
   云上白色按钮会重新失配——这类颜色范围应以官方云层为准，不要按本机截图改。
