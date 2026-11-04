# 排障

本页按「症状 → 诊断命令 → 结论」组织。每条结论都写成可验证的形式：先拿到失败节点名与识别分数，再判断是识别、点击、还是云会话层的问题，不靠猜。  
最后更新：2026-11-04

## 定位顺序

1. **先看汇总**：`run_daily_linux.py` 结尾会打印逐项结果与退出码，`probe_out/daily_linux_progress.jsonl` 里有 `last_node`、`timeout`、`attempt`。
2. **再看日志尾部**：运行日志在 `~/maaend/daily.log`（夜间链是 `nightly.log`），框架日志在 `$MAA_LOG_DIR`。
3. **分出三类**：节点根本没命中（识别问题）、命中了但点击无效（输入问题）、画面根本不在预期页面（会话问题）。三类的修法完全不同。
4. **留证据**：失败时框架会保留现场帧，正常跑完会清空 `vision/`。要复现就单跑那个任务，别在整链里找。

```bash
tail -n 200 ~/maaend/daily.log
grep -n "Failed\|timeout\|target rect is empty" ~/maaend-log/*.log | tail -30
pgrep -af "run_daily_linux|go-service|cpp-algo|chrome|sway"
```

## 症状速查

| 症状 | 先跑什么 | 常见结论 |
| --- | --- | --- |
| 启动即报「资源加载失败」 | `python web/linux/homesrv/post_upgrade_check.py` | 覆盖层有悬空 `next`，或平台层与发行版不同版 |
| 任务面板里没有自定义任务 | `grep -n "WebStartGame" assets/interface.json` | `import` 里缺任务，或语言包缺 `task.*.label` |
| 点击成功但画面不动 | `ls "$XDG_RUNTIME_DIR/wayland-1"` | cron 下缺 `XDG_RUNTIME_DIR`，输入没进会话 |
| agent 连不上、客户端阻塞 | `ls -l ~/maaend/agent/maafw` | `agent/maafw` 符号链接被升级冲掉 |
| 节点分数卡在阈值下 | 见「模板分数不够」一节 | 灰度与 RGB 差异、缺 `green_mask`、模板分辨率不对 |
| 任务超时但节点都命中 | `grep -n "custom action" ~/maaend-log/*.log` | 自定义动作报错（例如 `target rect is empty`） |
| 云会话掉回落地页 | `python web/linux/run_daily_linux.py --instance <名> --tasks WebStartGame` | 会话被回收，需要走恢复链重新拉起 |
| 收尾后仍有进程 | `pgrep -af "sway\|chrome\|go-service"` | `mh_cleanup` 被跳过，或进程名与 `pkill` 模式不符 |

## 模板分数不够

网页端的画面经过「1080p 串流 → 浏览器放大 → 合成器 → 720p」，与本地客户端截图不同源，掉分是常态。按顺序排：

1. **灰度 vs RGB**：MaaFramework 用灰度匹配。同一张模板实测 RGB NCC 0.9919、灰度只有 0.9013，阈值 0.95 就会反复失败。分数对不上时先用框架自己的匹配路径复核，不要拿别处的 RGB 分数当依据。
2. **`green_mask`**：地图总览入口 `MapOverviewEnter` 不套掩码只有 0.645，套上 0.992。
3. **小图标**：上游 `EnvironmentMonitoring/PhotoIcon.png` 在串流画面上只有 0.623（阈值 0.8），用网页截图重裁后能到 1.000 / 0.991 / 0.901。
4. **分辨率基准**：模板必须按 1280×720 标。抓帧长边被框架缩到 1280，改抓帧尺寸会让上游全部带框模板失效。

```bash
# 单节点评分与截图（只读，不点击）
python web/linux/homesrv/map_probe.py --help        # 地图界面节点级探针
python web/linux/devtools/hs_capture.py --help      # 抓一帧到文件，用来重裁模板
python web/linux/devtools/recapture_template.py --help  # 从当前画面重录模板
```

## 点击不生效

- cron 会话缺 `XDG_RUNTIME_DIR` 时，`sway` 会把 socket 落到 `/tmp/xdg-run`，点击不生效。`homesrv/lib.sh` 的 `mh_session` 会补 `/run/user/<uid>`；手工跑时自己 `export XDG_RUNTIME_DIR=/run/user/$(id -u)`。
- 指针累计到视口边缘后 `post_relative_move` 仍返回成功但画面不动。长任务前先回中，这是已知限制，不是节点问题。
- 用 `--controller cdp` 调试时，点击坐标要先换算到 CSS 坐标；没有 `<video>` 的页面（启动页）按视口尺寸换算，否则会出现「点击成功但游戏不启动」。

## agent 连不上

```bash
ls -l ~/maaend/agent/maafw            # 应指向 ~/maaend/maafw
ldd ~/maaend/agent/go-service | grep "not found"
echo "$LD_LIBRARY_PATH"               # 由 MAA_AGENT_LIB 拼出
```

`agent/maafw` 是符号链接，`auto_update.sh` 每次替换完会重建（`ln -sfn`）；如果手工替换过 agent，记得自己补。缺库时 go-service 报 `cannot open shared object file`，客户端表现为 `client.connect()` 永久阻塞，不是超时。

## AutoEssence 0/8

现象：基质链每轮都失败，逐项结果里 `AutoEssence` 的 `last_node` 停在 `GotoTriggerPointMove_VFTheHub`，日志里 `MapNavigateAction` 报 `custom action target rect is empty`，约 82 秒后 Failed。

```bash
grep -n "target rect is empty\|GotoTriggerPointMove" ~/maaend-log/*.log | tail -20
```

这条不是识别问题：前置的云版传送链已经通了（OCR 0.999974 → 模板 0.958905 → LOADING 0.992）。失败点在「自定义动作拿不到目标矩形」，要继续往上查 pipeline 传给 `MapNavigateAction` 的参数与 cpp-algo 侧的坐标换算。根因排序与复现命令见 [`diagnostics/autoessence-0of8.md`](./diagnostics/autoessence-0of8.md) 与 [`diagnostics/navigate-trigger-point.md`](./diagnostics/navigate-trigger-point.md)。

## EnvironmentMonitoring 卡地图锚点

现象：能从终端页走到地图，之后卡在 `__ScenePrivateMap*EnterWorldAnchorWithPick`；模板侧（地图、任务提示、地区总览、锚点图标）都命中。

```bash
python web/linux/homesrv/map_probe.py
```

怀疑点是 go-service 的 `MapFind`（世界坐标 → 屏幕坐标）在网页端地图上换算不对，先比较同一画面下 map_probe 打印的锚点屏幕坐标与地图实际位置。失败归因的完整过程见 [`env-monitoring-failure-attribution.md`](./env-monitoring-failure-attribution.md)。

## 云会话层

| 现象 | 说明 | 处理 |
| --- | --- | --- |
| 掉回落地页 | 云平台回收会话后画面回启动页，后续节点全部空转 | 状态机（默认开）会重新拉起登录链；`--no-state-machine` 可退回 pipeline 启动链对比 |
| 「上次游戏的数据正在火速处理中」 | 云会话没释放干净 | `WebSessionBusy` 点「知道了」后等 20 秒回入口重试 |
| 月卡 / 结算弹窗挡住画面 | 此时 `InWorld` 与 `InMenuList` 都不命中 | `WebMonthlyCard` / `WebCloseRewards` 负责点掉；不点会让整批任务超时 |
| 退出链空转 | 网页端没有可识别的关闭按钮时 ESC 连按会空转 300 秒 | `__ScenePrivateAnyExit` 把 `max_hit` 从 100 降到 6 |
| 分层地图切换掉分 | `MapLayersOther.png` 带黄色选中高亮条，单层地图没有该控件 | 未验证项，等取到「首墩内部」缩小态的画再定 |

## 部署与升级

| 现象 | 诊断 |
| --- | --- |
| 升级后大面积失败 | 看 `~/maaend/upgrade.log` 的「自检未通过，回滚」与 `option_drift.json` |
| 选项树改了导致覆盖失效 | `python web/linux/homesrv/option_audit.py --check` |
| cpp-algo 被换回新版 | `md5sum ~/maaend/agent/cpp-algo`，期望 `4056272952b61fe10a9e0a0e7484bbf5`（1.0856 版） |
| 任务卡住要人工接管 | `bash web/linux/homesrv/stop_homesrv.sh` |

## 静态检查失败

| 命令 | 常见原因 |
| --- | --- |
| `uv run ruff check web/linux` | `web/pyproject.toml` 用 `extend` 继承根配置；报错基本都是真的，不要往 ignore 里加规则 |
| `python -m unittest discover -s web/linux/tests` | 在仓库根执行；`ImportError: maaend_web` 说明没在仓库根或 `web/linux` 下跑 |
| `node --test web/linux/tests/*.test.mjs` | 需要 Node ≥ 22；用例与 `page_js.py` 共用同一份 JS 源码 |
| `shellcheck -x web/linux/homesrv/*.sh` | `-x` 必须带，否则 `source lib.sh` 里的变量会被当成未定义 |
| `pnpm exec markdownlint "web/**/*.md"` | 表格按紧凑格式写（`\| --- \|`）、代码块要带语言；历史目录按 CI 的 ignore 处理 |
| `pnpm exec prettier --check "web/**/*.json"` | 用 `pnpm exec prettier --write "web/**/*.json"` 修；`.prettierrc.mjs` 的 maafw 插件会按 pipeline / interface 两套语义排序键 |
