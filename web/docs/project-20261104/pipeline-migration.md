# 覆盖层迁移映射（sa-1，2026-11-04）

把 `web/resource_web` + `web/resource_web_homesrv` 的 36 个节点重组为 `assets/resource_cloud_web`（23 个），
并把 `assets/resource_cloud_adb` 按官方 `ba5887d64` 的 `assets/resource_cloud` 重建（30 个）。
节点级判定依据见同目录 `node-overlap.txt`；本文只回答「谁搬到了哪里」和「谁需要同步」。

## 1. 目标结构

```text
assets/
├── interface.json                  # Linux-Wlroots.attach_resource_path += resource_cloud / resource_cloud_web
├── resource/                       # 上游 base，未动
├── resource_cloud/                 # 原 resource_cloud_adb，按官方基线重建（30 节点）
├── resource_linux/                 # 上游 Linux 薄覆盖，未动
└── resource_cloud_web/             # 新增：网页端薄覆盖（12 文件 / 23 节点）
    ├── pipeline/
    │   ├── SceneManager/SceneLogin.json        # 启动链 5
    │   ├── SceneManager/SceneLoginDialog.json  # 标题页/月卡/会话弹窗 3
    │   ├── SceneManager/Exit.json              # ESC 退出链 3
    │   ├── SceneManager/SceneMap.json          # 云版传送 2
    │   ├── SceneManager/SceneMenu.json         # 进菜单 1
    │   ├── SceneManager/SceneWorld.json        # 结束拜访 1
    │   ├── Common/Button/Rewards.json          # 领奖弹窗 1
    │   ├── Interface/InScene/Region.json       # 菜单列表颜色 1
    │   ├── AutoEssence/CommonNodes/Capacity.json  # 2
    │   ├── EssenceFilter/Tab.json              # 2
    │   ├── ItemTransfer/Repo.json              # 1
    │   └── AutoStockpile/Entry.json            # 1
    └── image/
        ├── EnvironmentMonitoring/PhotoIcon.png  # base 节点用，云版重新抠图
        ├── WebTeleport/TeleportButtonCloud.png  # 云版传送胶囊（模板路径不能改：相对 image/ 解析）
        └── WebStartGame/StartButton.png         # 已退役的 TemplateMatch 变体，留作切回
```

目录命名沿用官方 `resource_cloud` 的写法：**覆盖 base 的节点镜像 base 的文件路径**（`AutoEssence/CommonNodes/Capacity.json`、
`Interface/InScene/Region.json`、`AutoStockpile/Entry.json`…），网页端独有的节点放在同名业务目录下（`SceneManager/SceneLogin*.json`、
`SceneManager/Exit.json`）。单文件 1–5 节点，未超过 7。

## 2. 节点映射（23 个保留节点）

| 新位置 | 节点 | 原文件 |
| --- | --- | --- |
| `assets/resource_cloud_web/pipeline/AutoEssence/CommonNodes/Capacity.json` | `AutoEssenceCapacityCursorPark` | `web/resource_web_homesrv` |
| `assets/resource_cloud_web/pipeline/AutoEssence/CommonNodes/Capacity.json` | `AutoEssenceCapacitySwitchToWeaponTab` | `web/resource_web_homesrv` |
| `assets/resource_cloud_web/pipeline/AutoStockpile/Entry.json` | `AutoStockpileGotoElasticGoods` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/Interface/InScene/Region.json` | `CheckMenuListColor` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/EssenceFilter/Tab.json` | `EssenceFilterCursorPark` | `web/resource_web_homesrv` |
| `assets/resource_cloud_web/pipeline/EssenceFilter/Tab.json` | `EssenceFilterSwitchTab` | `web/resource_web_homesrv` |
| `assets/resource_cloud_web/pipeline/ItemTransfer/Repo.json` | `ItemTransferRepoSwitchButton` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLogin.json` | `WebAlreadyInGame` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/Exit.json` | `WebAnyExitEsc` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/Exit.json` | `WebCloseProtocolPass` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/Common/Button/Rewards.json` | `WebCloseRewards` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLogin.json` | `WebLauncherStartButton` | `web/resource_web_homesrv` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLoginDialog.json` | `WebMonthlyCard` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLogin.json` | `WebQueueDetected` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLoginDialog.json` | `WebSessionBusy` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLogin.json` | `WebStartGameEntry` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLoginDialog.json` | `WebTitleContinue` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneLogin.json` | `WebWaitInGame` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/Exit.json` | `__ScenePrivateAnyExit` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneWorld.json` | `__ScenePrivateEndVisit` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneMap.json` | `__ScenePrivateMapTeleportConfirm` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneMap.json` | `__ScenePrivateMapTeleportSuccess` | `web/resource_web` |
| `assets/resource_cloud_web/pipeline/SceneManager/SceneMenu.json` | `__ScenePrivateWorldEnterMenuList` | `web/resource_web` |

删除的 13 个（与官方云层逐键相同，改由 `assets/resource_cloud` 提供）：

`AutoStockInStapleItem`、`CanAfford`、`DailyEventRecognitionRedDot`、`DailyEventUnread*Color` ×7、
`OutpostTradingZeroProductColorMatch`、`YellowButtonBackground`、
`__AutoUseSpMedicationColorRecognitionEmergencySanityBoosterDeadline`。

## 3. 删除的目录与文件

| 路径 | 说明 |
| --- | --- |
| `web/resource_web/` | 全部内容迁入 `assets/resource_cloud_web/`；其中 `pipeline/patch_cloud_ui_into_start.py`、`pipeline/patch_webstart_like_cloudadb.py`（一次性 patch 脚本）、`pipeline/__pycache__/`、`pipeline/DESIGN-WebStartGame.md`（设计草案，内容已并入本文 §5）随目录一起删 |
| `web/resource_web_homesrv/` | 5 节点并入；`image/WebStartGame/StartButtonCyan.png` 无任何引用，未搬 |
| `web/resource_web_pipeline/image/{WebStartGame/StartButton_x2,_x3,StartText}.png` | 未搬：无任何节点引用（旧 TemplateMatch 阈值试验的留档） |
| `web/linux/resource_web_min/`、`resource_web_structural/`、`resource_web_startup/` | 本地生成物（`web/linux/.gitignore` 里就是这三个），被误提交；目录与 `.gitignore` 条目一起删（`.gitignore` 随之变空并删除） |
| `web/linux/resource_web_cdp/` | 只有 `image/WebStartGame/StartButton.png`，无 pipeline；唯一引用是 `maaend_web/cli/daily.py` 里 `layer.is_dir()` 的软判断（目录不在就跳过），删掉不影响运行 |
| `web/linux/.gitignore` | 三条 ignore 对应上面三个目录，目录已删，文件随之删 |

## 4. 加载顺序（改路径的人看这里）

官方机制（`interface.json`）：`resource[].path` 先加载，再按 `controller[].attach_resource_path` 顺序逐层 post_bundle；
MaaFramework 的合并是**按节点名 patch**：后一层的同名节点以旧节点为 default 逐字段覆盖（`PipelineParser::parse_recognition`，
同类型时 param 逐键继承），所以覆盖层只写差异字段是对的。

```jsonc
"Linux-Wlroots": {
    "attach_resource_path": [
        "./resource_linux",
        "./resource_cloud",       // 网页端跑的是云·终末地，云层在这里生效
        "./resource_cloud_web"    // 网页端薄覆盖
    ]
}
```

我们自己的 Python 运行层不看 `interface.json`，走 `MAAEND_RES_DIRS`（四层深合并）。迁移后的默认值应为：

```bash
MAAEND_RES_DIRS=$ROOT/resource:$ROOT/resource_linux:$ROOT/resource_cloud:$ROOT/resource_cloud_web
```

要点三条：

1. `resource_cloud` 必须在 `resource_cloud_web` **之前**——13 个被删的颜色节点靠它提供。
2. 原 `web/resource_web_homesrv` 层已并入 `resource_cloud_web`（`WebLauncherStartButton` 只保留生产生效的 OCR 版），不再单独加载。
3. `web/linux/resource_web_linux`（只剩一张 StartButton.png，无 pipeline）已无意义，建议从链条里去掉并删除。

## 5. 已知影响与遗留

1. **生效差异 1 处**：`__ScenePrivateAnyExit` 的 `pre_delay` 由默认 200ms 变成 0（云层的同名节点是 fork 的点击版，自带 `pre_delay: 0`，
   我们的 ESC 版没有显式写这个字段，按 patch 语义继承下来了）。识别仍是 DirectHit、动作仍是 ESC，影响可忽略；若要去掉，
   在 `resource_cloud_web/pipeline/SceneManager/Exit.json` 里给它补 `"pre_delay": 200`。
2. **云层登录判据变化**：官方 `resource_cloud/SceneManager/SceneLogin.json` 把 `__ScenePrivateLogin` 的模板换成
   `AdbOnly/SceneManager/News.png`（该模板只在 `resource_adb` 里）。网页端不挂 `resource_adb`，所以这个节点在网络端是
   **有定义但永不命中**（MaaFramework 只在识别时查模板，缺模板不会导致 bundle 加载失败），等于网页端失去了 base 的 `LoginExit` 判据。
   当前生产链不依赖它（`WebStartGameEntry` 接管落地页/排队/标题页），但登录过期是需要补的（原设计草案里的 `WebLoginExpired`）。
3. **两个孤儿节点**：`WebAnyExitEsc`、`WebCloseProtocolPass` 当前没有任何 `next`/`all_of` 引用（原先的插入点已撤回，唯一提到它们的是
   已删除的 `resource_web_structural` 和 `split_overlay.py` 的名单）。保留在 `SceneManager/Exit.json` 里，接线或删除需要一次实测决策。
4. **`WebLauncherStartButton` 只剩 OCR 版**：`TemplateMatch` 变体（`image/WebStartGame/StartButton.png`、阈值 0.95）在云版配色下最高 0.486，
   已在节点注释里写明如何切回；`StartButton_x2/_x3/StartText` 是无引用的阈值试验留档，未搬。
5. **任务标签缺 i18n key**：`assets/tasks/WebStartGame.json` 用 `$task.WebStartGame.label/description`，5 个
   `assets/locales/interface/*.json` 都没有这两个 key，MAA 界面会直接显示占位符。

## 6. 验证

```bash
# 全部 JSONC 可解析（含官方带注释的文件）
python -c "import sys,glob;sys.path.insert(0,'web/linux');from maaend_web.jsonc import loads_jsonc;[loads_jsonc(open(f,encoding='utf-8').read()) for f in glob.glob('assets/resource_cloud*/**/*.json',recursive=True)]"

# 23 个保留节点逐键等于迁移前（对比迁移前快照）
# 36 个生效节点：按框架 patch 语义模拟加载，35/36 一致，唯一差异见 §5.1
```

详细数字见交付报告与 `node-overlap.txt`。
