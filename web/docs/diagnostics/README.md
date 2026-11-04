# 诊断（只读）

本目录只放**诊断结论与可复现证据**，不改任何 pipeline / 任务 / 运行层代码。
两个诊断脚本在 `web/linux/homesrv/`，只读：可以抓帧与读日志，不点击、不按键、不派发任务。

## 证据分级

每条结论都带 `evidence_class`，三种口径不能混用：

| 分级 | 含义 | 可否当作「当前代码的缺陷」 |
| --- | --- | --- |
| `static` | 代码/数据层可直接比对（文件:行号），与任何一次运行无关 | **可以** |
| `static`（deploy） | 部署机上「哪一层真正生效」的解析结果，同属数据层事实 | 可以，但依赖部署目录结构 |
| `log` | 某一轮日志里的观测，需先确认日志属于当前部署 | 需先看 `freshness.log_precedes_code` |
| `needs-live` | 只能在实机上复验（重跑任务、抓帧评分） | 不能，作为待办 |

脚本会自动比较「日志末条时间」与「代码 mtime」，日志早于代码部署时打 `E-STALE-LOG`/`N-STALE-LOG`，
并把同一条日志结论降级为 `warn`。**夜间链（11-04 03:00–04:22）跑的是部署前的旧 `web/linux`，
其中的失败不能当作重构版代码的证据。**

## 脚本

### diagnose_essence.py

AutoEssence 基质链：日志时间线（阶段到达 / 走位窗口 / 静默间隔）+ 云层与官方 `resource_cloud` 的文件·节点·字段差集 + **部署机实际层序**（按 `lib.sh` 的 `mh_res_dirs` 规则算哪个定义真正生效）+ 可选只读识别评分。

```bash
# 纯离线（无游戏、无 maa）
python3 web/linux/homesrv/diagnose_essence.py \
    --log ~/maaend/essence.log --root ~/maaend --repo ~/maaend \
    --official ~/maaend-official

# 机器可解析
python3 web/linux/homesrv/diagnose_essence.py --log ~/maaend/essence.log --json

# 追加只读评分：一次截图，只跑 post_recognition，不输入
python3 web/linux/homesrv/diagnose_essence.py --log ~/maaend/essence.log \
    --root ~/maaend --probe --sock /run/user/1000/wayland-1
```

### diagnose_navigate.py

走位链：把每次 `GotoTriggerPoint*` 尝试切成窗口（起点、用时、窗口内 MapNavigator 子任务、最长静默、
anchor 空转次数），并核对静态前置条件（cpp-algo 版本、转向系数、`base.nav.gz` 里的 zone、路线引用节点、
cpp-algo 日志目录）。

```bash
python3 web/linux/homesrv/diagnose_navigate.py \
    --log ~/maaend/essence.log --root ~/maaend --repo ~/maaend \
    --node GotoTriggerPointMove_VFTheHub

python3 web/linux/homesrv/diagnose_navigate.py --log ~/maaend/essence.log --json
```

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 未发现静态缺陷（日志侧无告警） |
| 1 | 有告警：旧部署日志、静默窗口、缺 cpp-algo 日志等 |
| 2 | 有静态阻断项（云层节点缺失/被覆盖、navmesh 缺 zone、二进制 md5 不符） |
| 3 | 用法或环境错误（日志/根目录不存在） |

## 结论

- [autoessence-0of8.md](autoessence-0of8.md)：AutoEssence 0/8 的静态已证项与待复验项
- [navigate-trigger-point.md](navigate-trigger-point.md)：`GotoTriggerPointMove_*` 走位失败的窗口与机制候选
- [cloud-layer-parity.md](cloud-layer-parity.md)：与官方 `resource_cloud` 的全量节点差集（含非 AutoEssence 文件）
- [cloud-layer-diff-baseline.json](cloud-layer-diff-baseline.json)：迁移前（`b8cda0c66`）差集的机器可解析快照
