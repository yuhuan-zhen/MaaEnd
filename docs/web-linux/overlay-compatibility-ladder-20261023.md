# 覆盖层兼容性阶梯（2026-10-23）

**要回答的问题**：别人在上游写的节点，我们能不能**一行不改直接跑**？

判据只有一条：**把我们的覆盖层逐层摘掉，摘到哪一层开始失败**。摘得越干净，兼容性越好。

---

## 1. 现在的 31 个节点，按「会不会和上游打架」分三层

`split_overlay.py` 会把 `web/resource_web/pipeline/nodes.json` 拆成三层：

| 层 | 节点数 | 内容 | 和上游的冲突性 |
|---|---|---|---|
| **`resource_web_min`** | 14 | 颜色阈值 / ROI / 时序（`lower`/`upper`/`roi`/`post_delay`） | **低**：只盖数值，字段名不变 |
| **`resource_web_structural`** | 3 | `next` 链、识别类型 | **高**：上游改同节点就冲突，是兼容性杀手 |
| **`resource_web_startup`** | 14 | 网页启动链（9）+ 网页挡屏（5） | 无（上游没有这些节点），但职责该归 launcher |

### 结构覆盖（3 个，最终目标清零）

| 节点 | 改了什么 | 消除手段 |
|---|---|---|
| `__ScenePrivateAnyExit` | `recognition: DirectHit` + `max_hit 100→6` + `post_delay 3000→600` | 网页有键盘；若上游能接受 ESC 直退就是通用优化，否则交给 agent 自定义动作 |
| `__ScenePrivateWorldEnterMenuList` | `next` 去掉 `__SceneImageCheck` | 图检在串流画面上不过；精确 1280×720 + 抹平注入后可能不再需要 |
| `SceneAnyEnterWorld` | `next` 插入 `WebCloseProtocolPass` | 通行证全屏页由 launcher `--prepare` 关掉，就不必改链 |

### 数值覆盖（14 个）

`CheckMenuListColor`、`CanAfford`、`AutoStockInStapleItem`、`AutoStockpileGotoElasticGoods`、
`DailyEventRecognitionRedDot`、7 个 `DailyEventUnread*Color`、`__AutoUseSpMedication…Deadline`、`__ScenePrivateEndVisit`。

这些是串流压缩/布局导致的色偏与位置差。**精确视口 + 画质拉满 + 抹平注入**之后，
预计能删掉一部分（尤其 `CheckMenuListColor` / `DailyEventRecognitionRedDot.roi` / `__ScenePrivateEndVisit.roi`
这几个是「网页外壳遮挡」导致的，注入藏掉外壳后应该回上游值）。

---

## 2. 阶梯怎么跑（在 homesrv 上）

```bash
cd /path/to/MaaEnd            # 仓库根
python3 web/linux/split_overlay.py --write     # 生成三层目录

BASE=$HOME/maaend/resource                      # 安装目录里的上游资源
MIN=$PWD/web/linux/resource_web_min
STRUCT=$PWD/web/linux/resource_web_structural
START=$PWD/web/linux/resource_web_startup
```

| 级 | 命令 | 想验证什么 | 预期 |
|---|---|---|---|
| **L0** | `MAAEND_RES_DIRS=$BASE python3 web/linux/run_daily_linux.py --only 3,4,5` | 纯上游节点能不能跑 | 大概率失败 → 说明覆盖层还在做实事 |
| **L1** | `MAAEND_RES_DIRS=$BASE:$MIN …` | 只加数值覆盖够不够 | 若通过：说明**结构覆盖其实可以不要** |
| **L2** | `MAAEND_RES_DIRS=$BASE:$MIN:$STRUCT …` | 加结构覆盖 | 若 L1 通过、L2 也通过，结构层就是冗余 |
| **L3** | 现状（`--controller cdp`，全量） | 基线 | 9/9 |

**判读规则**：

- **L1 通过** → 直接删掉 `resource_web_structural` 整层（3 个节点），兼容性问题一次解决；
- **L1 失败、L2 通过** → 逐条试：先用 `--no-overlay` 跑单任务定位是哪一处，
  再分别只保留 `AnyExit` / `WorldEnterMenuList` / `SceneAnyEnterWorld` 中的一个，看哪个是必需的；
- **L0 也通过** → 说明上游原版就能跑，我们连数值层都可以删（最理想，但要怀疑是不是没走到那些节点）。

单任务建议用 `3,4,5`（DijiangRewards / CreditShoppingN2 / AutoStockpile）——它们覆盖了颜色识别、菜单列表、时序三类。

---

## 3. 阶梯背后的三件改造（已完成 / 进行中）

| 改造 | 作用 | 状态 |
|---|---|---|
| **launcher `--prepare`**（页面状态机） | 启动链移出 pipeline → `resource_web_startup` 里 9 个节点可以删 | ✅ 状态机已做，launcher 草案支持 `--mode compositor/cdp` |
| **抹平注入**（`FLATTEN_JS`） | 藏悬浮球 / 延迟角标 / 网页外壳；视频铺满视口 | ✅ 已做，真浏览器 e2e 通过 |
| **精确 1280×720 / DSF=1** | 模板不用重裁，几何与 PC 对齐 | ✅ launcher 草案用 `Browser.setWindowBounds` 校正，实测 1280×720 |

---

## 4. 终态目标

```
resource_web_structural   → 0 个节点（兼容性目标）
resource_web_startup      → 0 个节点（launcher 接管）
resource_web_min          → 0～14 个节点（视画质而定，纯数值、无冲突）
```

达成后：
- 上游新增任务/节点**自动可用**，不需要我们跟；
- 上游改 `SceneAnyEnterWorld` 之类的主干节点**不会和我们冲突**；
- 我们的维护面只剩 launcher（~300 行 + 两个 JS）+ 少量颜色阈值。

---

## 5. 一个诚实的提醒

`resource_web_min` 里那些颜色阈值，是用**当前串流画质**采样出来的。如果网页端调整了编码参数
（码率、分辨率、色彩空间），这些阈值会重新飘——所以它们的正确维护方式是
「每次网页端大版本更新后跑一次颜色采样脚本」，而不是手工调。
