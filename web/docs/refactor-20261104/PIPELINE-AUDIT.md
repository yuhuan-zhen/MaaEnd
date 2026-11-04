# Pipeline 覆盖层审计报告（2026-11-04）

本文是重构组 E 的自审记录：把 `web/resource_web`、`web/resource_web_homesrv` 两层 pipeline 覆盖与 `tasks/` 下 8 个任务文件，逐条对照上游 pipeline 规范核对，并给出已修项、未修项与验证方式。报告只覆盖这两层资源与任务定义，不涉及 `web/linux` 代码与 `image/` 下的模板二进制。

结论：字段、类型、ROI 边界、引用闭合全部通过（0 违规、0 悬空引用；37 个节点定义、去重 36 个，在 MaaFramework 里三层加载均成功）；真正的偏差集中在「格式」与「文档/工具清单漂移」，以及 4 处 OCR `expected` 用正则但没加 `// @i18n-skip` 的规范缺口（该缺口与仓库里唯一的严格 JSON 消费方冲突，未擅自修改，见第 5 节）。

## 1. 审计范围

| 文件 | 节点/条目 | 行数 | 本次改动 |
| --- | --- | --- | --- |
| `web/resource_web/pipeline/nodes.json` | 32 个节点（21 个增量覆盖 + 11 个新增） | 677 | 已格式化、去 1 处重复项 |
| `web/resource_web_homesrv/pipeline/nodes.json` | 5 个节点（2 个增量覆盖 + 3 个新增） | 109 | 已格式化 |
| `tasks/AndroidOpenGame.json` | 1 任务 / 3 选项 | 175 | 无（格式已合规） |
| `tasks/CloseGamePC.json` | 1 任务 / 9 选项 | 519 | 无（格式已合规） |
| `tasks/CreditShopping.json` | 1 任务 / 40 个被覆盖节点 | 2469 | 无（格式已合规） |
| `tasks/DijiangRewards.json` | 1 任务 / 46 个被覆盖节点 | 1397 | 无（格式已合规） |
| `tasks/EssenceFilter.json` | 1 任务 / 6 个被覆盖节点 | 584 | 无（格式已合规） |
| `tasks/ProtocolSpace.json` | 1 任务 / 55 个被覆盖节点 | 1486 | 无（格式已合规） |
| `tasks/AutoEssence/AutoEssence.json` | 1 任务 / 23 个被覆盖节点 | 1045 | 无（格式已合规） |
| `tasks/pretasks/GameSetting.json` | 1 预任务 / 7 选项 | 218 | 无（格式已合规） |

合并去重后两层共 36 个唯一节点名（`WebLauncherStartButton` 在两层各定义一次，见 5.3）。

## 2. 规范依据

| 编号 | 来源 | 本报告用到的条款 |
| --- | --- | --- |
| S1 | `D:\maaend-upstream\.agents\skills\pipeline-guide\SKILL.md` | 核心原则 3（避免硬延迟）、4（720p 基准）、5（ prettier 格式化）；节点命名（`__` 内部前缀、任务名前缀）；OCR `expected` 必须完整文本、片段/正则要 `// @i18n-skip` + 完整原文注释；`[JumpBack]` 语义；审查清单 |
| S2 | `D:\maaend-upstream\.agents\skills\pipeline-guide\field-reference.md` | 通用字段表、各识别/动作参数字段表、`wait_freezes` 对象字段表、默认值 |
| S3 | `D:\maaend-upstream\.prettierrc.mjs` | JSON：4 空格、`bracketSameLine: false`、`trailingComma: none`；`multilineArraysWrapThreshold: 1`；`@nekosu/prettier-plugin-maafw-sort` 负责节点字段排序。注意：规范文档里写的 `.prettierrc` 实际文件名是 `.prettierrc.mjs`（仓库根另有 `.prettierignore`） |
| S4 | `D:\maaend-upstream\.agents\skills\docs-guide\SKILL.md` | 报告写法：一段一行、标识符行内代码、表格紧凑、代码块带语言 |
| S5 | `D:\maaend-upstream\deps\docs\zh_cn\3.1-任务流水线协议.md` | `roi` 支持字符串（节点名）与负数锚边；`expected` 为「任一命中」；`focus` 为 object；未声明字段静默忽略 |
| S6 | `D:\maaend-upstream\deps\docs\zh_cn\3.3-ProjectInterfaceV2协议.md` | `pretask` 允许出现在 `import` 的片段文件里、字段为 `exec/args/name/label/description/controller/option`；`option.inputs` 的 `verify`/`pattern_msg` |

## 3. 前置事实：覆盖层是「同名字段覆盖」的增量层

这条决定了后面所有「字段缺失算不算错」的判断，所以先用 MaaFramework 实测确认，而不是靠读代码猜。

用 `MaaFramework.dll` 的 C API（`MaaResourcePostBundle` + `MaaResourceGetNodeData`）把 `assets/resource`、`resource_web`、`resource_web_homesrv` 三层依次加载，再读回每个节点的最终形态：

| 节点 | 覆盖层写了什么 | 读回的最终形态 | 说明 |
| --- | --- | --- | --- |
| `CanAfford` | 只有 `lower` / `upper` | `recognition.type = ColorMatch`，`roi` 仍是 base 的 `"NotSoldOut"`，`roi_offset`/`count`/`method`/`order_by` 全部来自 base | 节点的其余字段按 key 继承 |
| `AutoStockInStapleItem` | `recognition.param` 里只给 `lower`/`upper`，不给 `type` | `type = ColorMatch`，`method: 40`、`count: 300` 来自 base | `recognition` 不给 `type` 时沿用 base 的类型与其参数 |
| `WebLauncherStartButton`（homesrv） | `recognition: {type: OCR, param: {expected, roi}}` | `type = OCR`，参数里**没有** base 的 `template`/`threshold` 残留 | 给了新 `type` 就按新类型重建参数 |

同一套 API 的隔离实验（每个用例单独一个 bundle，内含 `OkNode` + `Probe`）：

| 用例 | `post_bundle` | 节点是否可读 | 结论 |
| --- | --- | --- | --- |
| 未知顶层字段 `bogus` | 3000 成功 | 是 | 未知字段被静默忽略，不会报错 |
| `desc` 字段 | 3000 成功 | 是 | `desc` 合法 |
| 未知参数名（`templat`） | 3000 成功 | 是，参数被丢弃 | 参数名拼错是**静默失效**，最危险 |
| `roi: [1,2,3]` | 4000 失败 | 否，**整个文件被拒绝** | 值/类型错误会让整层 pipeline 不加载 |
| `recognition: "TemplatMatch"` | 4000 失败 | 否，**整个文件被拒绝** | 同上 |
| `target: "某节点名"`、`next: ["[JumpBack]X"]`、`focus` | 3000 成功 | 是 | 均合法 |

所以本文把「未知字段」定级为低风险（静默），把「类型/取值非法」定级为高风险（整层 32 个节点一起失效，任务会全部 20 秒超时），并且不把增量节点的字段省略当成缺陷。

## 4. 逐项结论

### 4.1 字段合法性

37 个节点定义（32 + 5）逐个核对 `recognition` / `action` / `next` / `on_error` / `pre_wait_freezes` / `post_wait_freezes` / `roi` / `target` 的类型与取值：**0 个非法字段、0 个非法类型**。

写法分布：v2（`{type, param}`）21 个、v1（`recognition` 为字符串、参数在节点顶层）16 个。两种混用是协议允许的（S5「同时兼容 v1」），上游也这么写（如 `Interface/InScene/Region.json` 的 `CheckMenuListColor` 是 v1，`SceneManager/SceneMenu.json` 的 `__ScenePrivateWorldEnterMenuList` 是 v2）。

有两类「看起来缺字段」的情况，按第 3 节结论都是合法的增量写法，但值得记录：

| 文件:行号 | 节点 | 写法 | 风险 |
| --- | --- | --- | --- |
| `nodes.json:346` | `AutoStockInStapleItem` | 只给 `recognition.param` 的 `lower`/`upper`，`type` 继承 base 的 `ColorMatch` | 中：上游若把该节点改成 v2 且换类型，这里会静默变成别的算法 |
| `nodes.json:406`、`418`、`455`…`539`、`551` | `CanAfford`、`YellowButtonBackground`、7 个 `DailyEventUnread*Color`、`OutpostTradingZeroProductColorMatch`、`__AutoUseSpMedicationColorRecognitionEmergencySanityBoosterDeadline` | 只有 `lower`/`upper`（或 `recognition.param.upper`），其余全继承 | 中：同上，且参数名拼错不会被框架报错（见 3 节的 `templat` 用例） |

另外 12 个节点没有 `desc`（`AutoStockInStapleItem`、`CanAfford`、`YellowButtonBackground`、`DailyEventRecognitionRedDot`、7 个 `DailyEventUnread*Color`、`OutpostTradingZeroProductColorMatch`）。`desc` 是可选字段，不构成本次违规，但覆盖层其它节点都写了「【网页端覆盖 · 理由】」，这 12 个没有说明，后续维护容易误删，建议后续补一行说明（见 5.6）。

### 4.2 ROI 基准

15 个节点带 `roi`，逐个按 1280×720 归一化后检查 `x+w<=1280`、`y+h<=720`：**0 个越界**。

其中 3 个用了负数，按协议（S5：`roi` 的负数从右/下边缘算起）归一化后都在画面内，不是笔误：

| 文件:行号 | 节点 | `roi` | 归一化后 | 判断 |
| --- | --- | --- | --- | --- |
| `nodes.json:5` | `CheckMenuListColor` | `[0, -200, 200, 200]` | `(0, 520, 200, 200)` 左下角 | 与 base 完全一致，负数是上游原写法 |
| `nodes.json:31` | `__ScenePrivateWorldEnterMenuList` | `[-200, 0, 200, 200]` | `(1080, 0, 200, 200)` 右上角 | 与 base 一致 |
| `nodes.json:196` | `WebTitleContinue` | `[-250, 200, 250, 400]` | `(1030, 200, 250, 400)` 右侧中部 | 新增节点，按「右侧对话框/标题区」取的范围 |

顺带修一处上游笔误的认知：`CheckMenuListColor` 上游 `desc` 写「左上角」，但 `roi` 是左下角；覆盖层已把 `desc` 改成「左下角」，与 `roi` 一致，本次保持不变。

### 4.3 OCR expected

7 个 OCR 节点的 `expected` 全部是「多语言整句 + 少量正则替代项」，符合 S1「默认写完整文本」；5 个节点含正则或片段，按 S1 需要 `// @i18n-skip` 与完整原文注释：

| 文件:行号 | 节点 | 现状 | 处置 |
| --- | --- | --- | --- |
| `nodes.json:235` | `WebSessionBusy` | `["知道了","知道了","确定","確定","(?i)OK","(?i)Got it"]`，`知道了` 重复 | **已修**：删掉重复项（去重后集合不变，OCR 是任一命中） |
| `nodes.json:264` | `__ScenePrivateEndVisit` | 含 `(?i)End\s*Visit`（真正则） | 未修，建议加 `@i18n-skip`，见 5.1 |
| `nodes.json:303` | `WebMonthlyCard` | 含 `(?i)Daily\s*Monthly\s*Pass\s*Rewards`、`(?i)Monthly\s*Pass\s*Day` | 未修，同上 |
| `nodes.json:580` | `WebCloseProtocolPass` | 含 `(?i)Pass\s*Rewards` | 未修，同上 |
| `nodes.json:636` | `ItemTransferRepoSwitchButton` | 含 `(?i)Switch\s*Depot`，另有单字片段 `Switch`、`Depot` | 未修，同上；这两个片段是「OCR 把标题拆成两行」的兜底，删掉会收窄命中，不能动 |

另有 2 个节点只有 `(?i)` 大小写标志、正文是完整词（`WebSessionBusy` 的 `(?i)OK`/`(?i)Got it`），以及 `WebQueueDetected:148` 里的 `Waiting`/`queue` 这种整词，按上游主流写法（见 4.3.1）不需要 `@i18n-skip`。

#### 4.3.1 为什么不给这 4 个节点直接加注释

S1 要求片段/正则加 `// @i18n-skip`，但本仓库有一个严格 JSON 消费方：`web/linux/split_overlay.py:58` 用 `json.load()` 读 `web/resource_web/pipeline/nodes.json`。一旦写入 `//` 注释，这个脚本会直接抛 `JSONDecodeError`，而它不在本组的可写范围内（PLAN 第 6 节分组表把 `web/linux/*.py` 划给 B/C 组）。

同时上游自己的实践也是「只有纯正则/纯片段才加」：`assets/resource/pipeline` 下含 `(?i)` 的 `expected` 块共 1117 处，其中只有 71 处带 `@i18n-skip`（如 `AccountSwitch.json:147` 的 `.*\d{4}.*`、`AutoEssence/CommonNodes/AutoEssence.json:461` 的空串）。带 `(?i)` 的多语言整句列表（例如 `AccountSwitch.json:84` 的 `确认退出/確定登出/(?i)Log out of`）一律不加。

结论：这是「规范条款」与「本仓库工具链」的冲突，需要先决定走哪条路（见 5.1），不擅自写入会让现有工具失效的注释。

### 4.4 next 列表与强制分支

35 条引用（`next` 27 条 + `all_of`/`any_of` 8 条）全部能在「base ∪ 覆盖层」里解析到，**0 条悬空**。覆盖层没有使用任何 `[JumpBack]` 前缀，逐条判断如下：

| 文件:行号 | 节点 | `next` | 判断 |
| --- | --- | --- | --- |
| `nodes.json:72` | `WebStartGameEntry` | 6 个分支（失活弹窗/月卡/已在游戏/标题页/排队/开始按钮） | 合理：这是「一次点击覆盖整条启动链」的入口，`timeout: 600000` 让它在黑屏加载期持续轮询，不是硬依赖 |
| `nodes.json:108`/`137`/`190` | `WebLauncherStartButton`、`WebQueueDetected`、`WebTitleContinue` | 4 个分支，末位是 `WebWaitInGame`（终态） | 合理：分支之间互为兜底 |
| `nodes.json:224` | `WebSessionBusy` | `["WebStartGameEntry"]` | **风险（中）**：`WebStartGameEntry` 是 `DirectHit`，必然命中，形成 `SessionBusy → Entry → SessionBusy` 的无上限环。弹窗一直在时每圈 `post_delay 20000`，可以空转数小时，且不吃 `max_hit` |
| `nodes.json:291` | `WebMonthlyCard` | `["WebStartGameEntry"]` | 同上，但有 `max_hit: 5` 兜底，风险低 |
| `nodes.json:568` | `WebCloseProtocolPass` | `["SceneAnyEnterWorld"]` | **风险（中）**：非 `[JumpBack]` 的硬依赖，20 秒内认不到 `SceneAnyEnterWorld` 就整节点判负；而且该节点目前在仓库内**没有任何调用方**（见 5.2），是死节点 |
| `nodes.json:606` | `AutoStockpileGotoElasticGoods` | `["AutoStockpileSelectMarket"]` | 合理：单链推进 |
| `nodes.json:26` | `__ScenePrivateWorldEnterMenuList` | `["__ScenePrivateAnyEnterMenuListSuccess"]` | 合理：上游是两项（多一个 `__SceneImageCheck`），这里是刻意删掉自检链 |
| `nodes.json:19`/`64` | `AutoEssenceCapacityCursorPark`、`EssenceFilterCursorPark`（homesrv） | 各 1 项 | 合理：这两条链是「点页签 → 挪指针 → 回原判据」，`post_wait_freezes: 200` 等画面稳定，比硬延迟正确 |

`WebTitleContinue` 的 `next` 里带自引用 + `max_hit: 10`，与上游 `__ScenePrivateLoginContinue` 的「点击循环」模式一致，不改。

### 4.5 节点命名

| 类别 | 数量 | 例子 | 结论 |
| --- | --- | --- | --- |
| `Web*` 新增入口/挡屏节点 | 11 | `WebStartGameEntry`、`WebLauncherStartButton`、`WebMonthlyCard`、`WebCloseRewards`、`WebAnyExitEsc`、`WebCloseProtocolPass` | 合规：模块前缀统一，S1「同一任务内以任务名/模块名为前缀」 |
| `__ScenePrivate*` 覆盖 base 内部节点 | 5 | `__ScenePrivateWorldEnterMenuList`、`__ScenePrivateEndVisit`、`__ScenePrivateAnyExit`、`__ScenePrivateMapTeleportConfirm`/`Success` | 合规：与 base 同名，S1 要求「不对外暴露」的 `__` 前缀保持 |
| 无前缀同名覆盖 | 16 | `CheckMenuListColor`、`CanAfford`、`ItemTransferRepoSwitchButton`、`__AutoUseSpMedication`… 系列 | 合规：覆盖层必须与 base 同名才能生效 |
| 新增辅助节点 | 2 | `AutoEssenceCapacityCursorPark`、`EssenceFilterCursorPark`（homesrv） | 低风险：按任务名前缀命名，但它们是纯内部辅助节点，按 S1 更适合 `__` 前缀（改动会牵动 `next`，收益低，仅记录） |

覆盖层 32 个节点里 21 个能在上游找到同名定义，11 个是新增（全部 `Web*`）；homesrv 5 个里 2 个同名、3 个新增。没有出现「引用了 `__ScenePrivate*` 内部节点做跨层入口」的情况（S1 审查清单最后一条）。

### 4.6 JSON 格式

改前 `resource_web` 是 1 空格缩进 + 键名按字母序（`count, desc, lower, post_delay, …`），`homesrv` 是 2 空格 + 手写顺序；两者都过不了 `prettier --check`。

改后用上游 `prettier 3.8.3` + `.prettierrc.mjs`（含 `@nekosu/prettier-plugin-maafw-sort`）格式化：4 空格缩进、数组逐元素换行、节点字段按插件规范序排列（`desc, max_hit, recognition, pre_wait_freezes, pre_delay, action, post_wait_freezes, post_delay, timeout, rate_limit, next, focus`）。格式化后 `prettier --check` 两个文件均通过。

字段顺序与上游的一致性：21 个同名节点里 19 个的键序列是上游同名节点键序列的子序列（同一插件规则产出，多写字段会插到规范位置）；另一个 `__ScenePrivateAnyExit`（多写了 `recognition`）与 `ItemTransferRepoSwitchButton`（多写了 `desc`/`pre_delay`/`post_delay`/`rate_limit`）是「字段超集」，插入位置也符合同一规则。例如 `CheckMenuListColor` 现在是 `desc, recognition, roi, lower, upper, count, pre_delay, post_delay, rate_limit`，与 `Interface/InScene/Region.json` 逐字相同。

### 4.7 任务文件

8 个文件与上游 `assets/tasks/` 同名文件逐字段比对：

| 文件 | 与上游关系 | 结论 |
| --- | --- | --- |
| `AndroidOpenGame.json`、`CloseGamePC.json`、`EssenceFilter.json`、`ProtocolSpace.json`、`AutoEssence/AutoEssence.json` | 内容与上游当前 HEAD 完全一致（0 差异） | 无需改动 |
| `CreditShopping.json` | 仅 1 处本地改动：`CreditShoppingClueSend` 的 `verify` 由 `^\d+$` 收紧为 `^(?:0\|[1-9]\|1\d\|20)$`，并补 `pattern_msg` | 合理（把「线索赠送上限」限制在 0–20），保留 |
| `DijiangRewards.json` | 仅 1 处本地改动：`ClueSend` 的 input 补 `verify` 与 `pattern_msg`（上游无校验） | 合理，保留 |
| `pretasks/GameSetting.json` | 上游没有这个文件 | **风险（高）**，见 5.4 |

格式：8 个文件 `prettier --check`（interface 模式）全部通过，无需格式化。

JSON 方言：`CreditShopping.json`（15 处，首处 2218 行）、`ProtocolSpace.json`（13 处）、`AutoEssence/AutoEssence.json`（13 处）含 `//` 注释，属 JSONC；其余 5 个是严格 JSON。这解释了为什么 `python json.load` 只在 `CreditShopping.json` 上失败——不是文件坏了，是方言不同，任何严格 JSON 校验都要换成 JSONC 解析器（PLAN 第 4 节规划的 `maaend_web/jsonc.py`）。

## 5. 已修与未修清单

### 5.1 已修

| 文件:行号 | 改前 | 改后 | 依据 | 风险 |
| --- | --- | --- | --- | --- |
| `web/resource_web/pipeline/nodes.json`（整文件） | 1 空格缩进、键名字母序，`prettier --check` 失败 | 4 空格、数组逐元素换行、字段按 `maafw-sort` 规范序，`--check` 通过 | S1 核心原则 5、S3 | 低：`json.load` deep-equal 通过；三层加载后 36 个节点里 35 个最终形态逐字节不变 |
| `web/resource_web_homesrv/pipeline/nodes.json`（整文件） | 2 空格缩进、手写键序，`--check` 失败 | 同上 | S1、S3 | 低：deep-equal 完全一致（0 差异） |
| `web/resource_web/pipeline/nodes.json:235-240` | `expected` 里 `知道了` 出现两次 | 只保留一次 | S1（去重不改判据；OCR `expected` 是任一命中，`order_by` 未用 `Expected`） | 低：MaaFramework 读回的 `expected` 仅少一个重复项 |

### 5.2 未修：死节点与文档漂移（不在本组可写范围）

| 位置 | 现状 | 依据/证据 | 建议 | 风险 |
| --- | --- | --- | --- | --- |
| `web/resource_web/pipeline/nodes.json:568` `WebCloseProtocolPass` | 仓库内无任何节点引用它（`next`/`all_of`/`any_of` 均无），`SceneAnyEnterWorld` 覆盖已在 `5579178` 删除 | 本报告 4.4 的引用清点；`docs/cloud-web-20261026/修复方案-20261026.md` 第 5 节「首选：删掉 `SceneAnyEnterWorld` 键」 | 保留节点定义（不增删节点是本次约束），若确认不再需要可单独提 PR 删除 | 低 |
| `README.md:41`、`README.md:47`、`README.md:51` | 写「`web/resource_web_homesrv/` 服务器特有覆盖（1 节点）」（实际 5 个）；列出 `__ScenePrivateCloudBackPill`、`__ScenePrivateCloudClickToContinue`（两个节点在仓库里都不存在）；写「`SceneAnyEnterWorld`：只插入一个 `WebCloseProtocolPass`」（无此覆盖） | `grep -r` 全仓库无这两个节点名；`nodes.json` 无 `SceneAnyEnterWorld` 键 | 更新 README 的描述与数量 | 低（只影响阅读） |
| `web/linux/split_overlay.py:32-48` | `STARTUP` 里 `WebTitleClickToContinue` 不存在（真实节点名 `WebTitleContinue`）；`BLOCKER` 里两个 `__ScenePrivateCloud*` 不存在；`STRUCTURAL` 仍列 `SceneAnyEnterWorld`（已删） | 同上 | 按实际节点名修名单，否则分层验证会把新 `Web*` 节点误报成「未归类」 | 低（仅离线验证脚本） |

### 5.3 未修：同名节点两层定义

`WebLauncherStartButton` 在 `resource_web`（`TemplateMatch`，`threshold: 0.95`，`nodes.json:108`）与 `resource_web_homesrv`（`OCR`，`expected: ["开始游戏"]`，`homesrv nodes.json:2`）各定义一次。加载顺序是 `resource → resource_web → resource_web_homesrv`（`web/linux/homesrv/daily_run_homesrv.sh:30`），后者覆盖前者，实测最终形态是 OCR 版，无残留字段（第 3 节第三个用例）。

保留：这是 homesrv 有意的变体（`desc` 里写了「原 TemplateMatch 在当前配色下最高只有 0.486」），两侧都有实测依据。仅提示风险：**同一节点名在两个文件里语义不同**，改其中一处时容易漏掉另一处。

### 5.4 未修：`tasks/pretasks/GameSetting.json` 当前不可能生效，且一旦生效会让客户端启动失败

| 事实 | 证据 |
| --- | --- |
| 该文件声明 `exec: "agent/go-service"`、`args: ["--pretask", "GameSetting"]` | `tasks/pretasks/GameSetting.json:6-10` |
| 上游 `interface.json` 的 `import` 只列了 `tasks/pretasks/LaunchGamePC.json`，没有 `GameSetting.json` | `assets/interface.json` 的 `import` 数组；`grep -c GameSetting assets/interface.json` = 0 |
| 部署补丁也没有改 `interface.json` | `patches/diff-vs-upstream-v2.35.0-beta.1.patch` 里无 `interface.json` 条目 |
| go-service 只注册了 `LaunchGamePC` 这一个预任务 | `agent/go-service/pretask/pretask.go:13-15`（`Register("LaunchGamePC", ...)`），`registry` 里没有 `GameSetting`；未注册时 `Run` 走 `log.Fatal("Unknown pretask")` 并以非零退出 |

按 PI V2 协议（S6）「预任务启动失败或返回非零退出码，Client 应中止本次启动并向用户报告错误」，所以：现在它是死文件（不会被 import），**一旦有人把它加进 `import`，MXU 启动会直接失败**。处置建议：要么等 go-service 补 `GameSetting` 预任务处理器后再 import，要么先删文件避免误接。本次不动（属产品决策，且删文件不在「不新增/不删除节点」的范围内）。

### 5.5 未修：硬延迟（S1 核心原则 3）

覆盖层有 7 处 `post_delay >= 600`，其中 3 处是「点击后靠等待代替识别」，属于 S1 明确不推荐的做法。它们都有实测背景（弹窗动画、页面切换），改任何一处都要实机验证，故只列不改：

| 文件:行号 | 节点 | 现状 | 风险 | 建议 |
| --- | --- | --- | --- | --- |
| `nodes.json:224` | `WebSessionBusy` | `post_delay: 20000` | 中（最大） | 换成 `post_wait_freezes` 或让 `next` 直接回 `WebStartGameEntry` 靠识别推进；需实机确认弹窗消失耗时 |
| `nodes.json:291` | `WebMonthlyCard` | `post_delay: 1500` | 低 | 同上 |
| `nodes.json:274` | `WebCloseRewards` | `post_delay: 1200` | 低 | 同上 |
| `nodes.json:334` | `WebAnyExitEsc` | `post_delay: 800` | 低 | ESC 后等界面反应，可改 `post_wait_freezes: 200` |
| `nodes.json:568` | `WebCloseProtocolPass` | `post_delay: 700` | 低 | 死节点，可不动 |
| `nodes.json:606` | `AutoStockpileGotoElasticGoods` | `post_delay: 800`（上游是 0，这是覆盖层唯一加进去的纯延迟） | 中：上游若把这一步改成识别驱动，这里的 800ms 会一直叠着 | 建议加注释说明原因；若上游已有 `AutoStockpileEnaureElasticClicked` 判据，可去掉延迟 |
| `nodes.json:322` | `__ScenePrivateAnyExit` | `post_delay: 3000 → 600` | — | 已是从 3000 降下来的，保持 |

### 5.6 未修：12 个增量节点没有 `desc`

见 4.1。建议后续补「【网页端覆盖 · 为什么】」，与其余 20 个节点的写法保持一致；不影响运行，故本次不动（避免在审计 PR 里塞入无实测支撑的说明文字）。

### 5.7 未修：OCR `@i18n-skip`（待决策）

见 4.3.1。两个选项：

1. **加注释**：在 4 个节点的 `expected` 数组内写 `// 完整原文：End Visit` + `// @i18n-skip`，同时把 `web/linux/split_overlay.py:58` 的 `json.load` 换成 JSONC 解析（PLAN 第 4 节要新增的 `maaend_web/jsonc.loads_jsonc` 正好可复用）。需要 B/C 组配合，且本报告要求的「每个改过的 JSON 用 `json.load` 验一遍」将不再适用。
2. **不加注释**：与上游 1046 处同类写法保持一致，仅在本报告登记缺口。

建议选 2 直到覆盖层真正接入 i18n 工具链（本仓库没有 `locales/`，也没有任何脚本跑 i18n，注释目前是零收益）；如果主代理要求严格对齐 S1 条款，则按选项 1 执行，改前/改后与依据已在上表写清。

## 6. 验证记录

### 6.1 严格 JSON 解析（两个改过的文件）

```text
$ python -c "import json;json.load(open('web/resource_web/pipeline/nodes.json',encoding='utf-8'))"
resource_web json.load OK
$ python -c "import json;json.load(open('web/resource_web_homesrv/pipeline/nodes.json',encoding='utf-8'))"
homesrv json.load OK
```

### 6.2 格式化 + 去重前后 deep-equal

脚本 `verify_deepequal.py`（临时文件，未提交）对每个文件比较节点集合、键顺序与逐字段值，白名单只放 `WebSessionBusy.expected`：

```text
[resource_web] json.load OK  before=32 nodes  after=32 nodes
  键顺序一致: True   差异条目: 1
   差异: WebSessionBusy recognition
      before: {"type": "OCR", "param": {"expected": ["知道了", "知道了", "确定", "確定", "(?i)OK", "(?i)Got it"], "roi": [350, 300, 620, 340]}}
      after : {"type": "OCR", "param": {"roi": [350, 300, 620, 340], "expected": ["知道了", "确定", "確定", "(?i)OK", "(?i)Got it"]}}
  白名单外差异: 无
[homesrv] json.load OK  before=5 nodes  after=5 nodes
  键顺序一致: True   差异条目: 0
  白名单外差异: 无

结论: 格式化 + 去重之外无语义变化
```

### 6.3 prettier

```text
$ node node_modules/prettier/bin/prettier.cjs --config .prettierrc.mjs --check <两个 nodes.json>
use pipeline mode
use pipeline mode
All matched files use Prettier code style!
```

`tasks/` 8 个文件同样 `--check` 通过（`use interface mode` × 8，`All matched files use Prettier code style!`）。

### 6.4 运行期一致性（MaaFramework 三层加载）

`dump_nodes.py` 在格式化前后各跑一次：`assets/resource` + `resource_web` + `resource_web_homesrv` 三层 `post_bundle` 全为 3000（成功），36 个节点全部可读，逐节点比较最终 JSON：

```text
层状态 before: {'resource': 3000, 'resource_web': 3000, 'resource_web_homesrv': 3000}
层状态 after : {'resource': 3000, 'resource_web': 3000, 'resource_web_homesrv': 3000}
节点集合一致: True | 节点数: 36 36
最终解析结果有差异的节点: ['WebSessionBusy']
   WebSessionBusy recognition
    before: {"param": {..., "expected": ["知道了", "知道了", "确定", "確定", "(?i)OK", "(?i)Got it"], ...}}
    after : {"param": {..., "expected": ["知道了", "确定", "確定", "(?i)OK", "(?i)Got it"], ...}}
```

即：格式化不改变任何节点在框架里的最终形态，唯一差异是 5.1 表里那条去重。

### 6.5 结构与引用校验

`final_check.py`（临时文件）对两个文件重算字段合法性、ROI 边界与引用闭合：

```text
计数: {'节点': 37, 'v1': 16, 'v2': 21, '增量': 23, '新节点': 14, 'roi': 15, '引用': 35}
错误: 0
提示（负 ROI 非越界，按协议为边缘锚点）: 3
引用解析不到: 无
```

其中 `增量 23 / 新节点 14` 是两层合计（`WebLauncherStartButton` 在两层各计一次），按层拆开是 `resource_web` 21 + 11、`homesrv` 2 + 3。

### 6.6 空白与行尾

```text
$ git diff --check
（无输出，退出码 0）
```

工作区 `core.autocrlf = true`，`nodes.json` 检出为 CRLF（677 行、677 个 CRLF、0 个裸 LF），与仓库其它文本文件（如 `tasks/CreditShopping.json`）一致，未改变行尾风格。

## 7. 参考的上游节点路径

对比时逐个取的 base 定义（`D:\maaend-upstream\assets\resource\pipeline\` 下）：

| 覆盖层节点 | 上游文件 |
| --- | --- |
| `CheckMenuListColor` | `Interface/InScene/Region.json` |
| `__ScenePrivateWorldEnterMenuList` | `SceneManager/SceneMenu.json` |
| `__ScenePrivateEndVisit` | `SceneManager/SceneWorld.json` |
| `__ScenePrivateAnyExit` | `SceneManager/SceneCommon.json` |
| `__ScenePrivateMapTeleportConfirm`、`__ScenePrivateMapTeleportSuccess` | `SceneManager/SceneMap.json` |
| `AutoStockInStapleItem` | `AutoStockStaple/General/Item.json` |
| `CanAfford` | `CreditShopping/Item/ShelfBase.json` |
| `YellowButtonBackground` | `Common/Button/ButtonColor.json` |
| `DailyEventRecognitionRedDot` | `DailyRewards/Event.json` |
| `DailyEventUnread*Color`（7 个） | `DailyRewards/Event/{ChallengeEvent,GiftEvent,GuideEvent,LimitedTimeEvent,LimitedTimeSignin,SpaceExplorationEvent,WeeklyRoutine}.json` |
| `OutpostTradingZeroProductColorMatch` | `OutpostTrading/SellCore.json` |
| `__AutoUseSpMedicationColorRecognitionEmergencySanityBoosterDeadline` | `Common/Private/AutoUseSpMedication/Recognition.json` |
| `AutoStockpileGotoElasticGoods` | `AutoStockpile/Entry.json` |
| `ItemTransferRepoSwitchButton` | `ItemTransfer.json` |
| `AutoEssenceCapacitySwitchToWeaponTab` | `AutoEssence/CommonNodes/Capacity.json` |
| `EssenceFilterSwitchTab` | `EssenceFilter.json` |
| `Web*`（11 个）、`AutoEssenceCapacityCursorPark`、`EssenceFilterCursorPark` | base 里无同名节点，属新增（`WebLauncherStartButton` 的 homesrv 版覆盖的是 `resource_web` 的同名节点） |

共性对照：上游同名节点的 `desc` 都是「一句行为说明」，覆盖层统一加了「【网页端覆盖 · 云串流适配】」前缀并附实测数据，这个写法本身没问题（`desc` 是自由文本），只是让 diff 变大。

## 8. 遗留

1. 4 处 `@i18n-skip` 缺口待主代理决策（5.7），涉及 `web/linux/split_overlay.py` 的 JSONC 改造。
2. `GameSetting` 预任务需要 go-service 侧配合，否则不能 import（5.4）。
3. README 与 `split_overlay.py` 的节点名清单与实际不符（5.2），属文档/工具漂移，未在本组可写范围。
4. 3 处「点击后用等待代替识别」需要实机验证后再改（5.5）。
5. 本报告是 `docs/refactor-20261104/` 下的内部中文文档（与 `PLAN.md` 同目录），不涉及 `docs/zh_cn` / `docs/en_us`，按 docs-guide 不需要中英同步。
