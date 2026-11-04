# 部署

本页说明部署形态、日常入口、自动更新与回滚、故障恢复。命令都在仓库根执行，`~/maaend` 是部署机上的发行版根。  
最后更新：2026-11-04

## 部署形态

部署机上是「发行版 + 本仓库」两层叠加：发行版（`resource/`、`interface.json`、`agent/`、`maafw/`）由 `auto_update.sh` 管理，本仓库的 `web/` 只放运行层与覆盖层脚本，升级不覆盖它。

```text
~/maaend/                        发行版根
├── resource/                    上游任务节点、模板、模型（720p 基准）
├── interface.json               任务与控制器声明
├── agent/{go-service,cpp-algo}  两个 agent 可执行文件
├── maafw/                       框架运行库
├── tasks/                        发行版任务定义（升级时同步）
├── config/mxu-MaaEnd.json       MXU 预设：任务顺序与选项，运行层的输入
├── web/                         本仓库的 web/
├── backups/<时间戳>/            自动更新的备份，保留最近 4 份
├── patches/agent/cpp-algo-1.0856.bin   cpp-algo 固定版本（见下）
├── daily.log / essence.log / nightly.log / upgrade.log
└── daily.conf / essence.conf    部署机本地配置（仓库里没有，缺省用脚本默认值）
```

资源挂载由 `assets/interface.json` 的 `controller[].attach_resource_path` 声明；`web/` 侧的路径、端口、超时集中在 `web/linux/maaend_web/config.py`，环境变量名见 [`../linux/README.md`](../linux/README.md#环境变量)。

## 一键部署

`homesrv/deploy.sh` 把「部署到 `~/maaend`」收成一条命令：备份 → 同步 → 语法检查 → 叠回覆盖层 → `--dry-run` 行为自检 → 打印回滚命令。它只同步仓库自己拥有的东西（`web/` 与 `assets/`），不碰发行版的 `resource/`、`interface.json`、`agent/`、`maafw/`——那几样由 `auto_update.sh` 负责。

```bash
./web/linux/homesrv/deploy.sh --dry-run              # 只打印计划 + 只读预检，不写任何文件
./web/linux/homesrv/deploy.sh                        # 本地部署到 $MAAEND_DIST 或 ~/maaend
./web/linux/homesrv/deploy.sh --remote homesrv       # 从 Windows/WSL 推到 homesrv，再在远端执行
./web/linux/homesrv/deploy.sh --dest ~/maaend-test   # 换目标，做灰度或演练
```

| 选项 | 作用 |
| --- | --- |
| `--src DIR` | 仓库根（默认从脚本位置往上三级推） |
| `--dest DIR` | 部署目录（默认 `$MAAEND_DIST` → `$MAAEND_ROOT` → `~/maaend`） |
| `--remote HOST` | 远端模式：`tar` 推送 `web/` 与 `assets/` 到临时目录后在那边跑 |
| `--yes` | 不询问；非 tty（双击、cron）下必须给 |
| `--keep N` | 部署备份保留份数，默认 4 |
| `--no-selfcheck` | 跳过部署后的 `run_daily --dry-run` 行为自检（不推荐） |

退出码：`0` 成功、`1` 用户取消、`2` 用法错误、`3` 预检失败、`4` 备份失败、`5` 同步失败、`6` 部署后检查失败（语法 / import / 覆盖层）、`7` 行为自检失败。换机器先跑 `--dry-run`，读一遍它打印的计划再真部署。

## 首次部署

1. 把发行版解到 `~/maaend`，确认 `resource/pipeline/nodes.json`、`interface.json`、`agent/go-service`、`maafw/` 都在。
1. 把本仓库的 `web/` 放到 `~/maaend/web`，`python3 -c "import sys;sys.path.insert(0,'web/linux');import maaend_web.config"` 能过即包结构完整。
1. 在 MXU 里配好日常任务与选项，导出 `~/maaend/config/mxu-MaaEnd.json`。运行层只读这份预设，没有它连 `--dry-run` 都跑不了。
1. 机器前置：headless sway、Chrome（或 Chrome for Testing）、Python ≥ 3.12；cron 会话需要能拿到 `XDG_RUNTIME_DIR`，`lib.sh` 的 `mh_session` 会补齐。
1. 不连游戏先自检：

    ```bash
    python -m unittest discover -s web/linux/tests
    uv run ruff check web/linux
    ```

1. 单任务试跑，确认启动链与登录链通：

    ```bash
    MAAEND_ROOT=$HOME/maaend python web/linux/run_daily_linux.py --instance hmuddz8 --tasks WebStartGame --attempts 1
    ```

1. 再上全量：`bash web/linux/homesrv/daily_run_homesrv.sh`。

`daily.conf` / `essence.conf` 是可选的部署机覆盖文件，脚本 `source` 它来改 `ROOT`、`TASKS`、`INSTANCE` 这类机器相关值；仓库里不放这两个文件。

## 日常入口

| 场景 | 命令 |
| --- | --- |
| 全量日常 | `bash web/linux/homesrv/daily_run_homesrv.sh` |
| 只跑几项 | `MAAEND_TASKS=WebStartGame,AutoStockpile bash web/linux/homesrv/daily_run_homesrv.sh` |
| 基质独立链 | `bash web/linux/homesrv/essence_run_homesrv.sh` |
| 夜间总调度 | `bash web/linux/homesrv/nightly_run_homesrv.sh` |
| 中途停止并收尾 | `bash web/linux/homesrv/stop_homesrv.sh` |

部署机上的 cron 只需一条，夜间链自己串行跑「更新 → 日常 → 基质」：

```cron
0 3 * * * /bin/bash "$HOME/maaend/web/linux/homesrv/nightly_run_homesrv.sh"
```

三个入口都靠 `homesrv/lib.sh` 的 `mh_cleanup` 收尾（`trap` 注册在 `EXIT` / `INT` / `TERM`）：先通知服务端结束会话，再关 Chrome、agent、浮层、合成器，最后打印 `chrome=0 agent=0 sway=0` 的残留计数。收尾不正常时先看这一行。

## 自动更新与回滚

`homesrv/auto_update.sh` 每天跟着上游走，规则是「绝不让更新把日常跑挂」：

| 行为 | 说明 |
| --- | --- |
| 只查版本 | 版本没变直接退出，不下载（包是 400MB 级） |
| 有任务在跑就跳过 | `pgrep run_daily_linux.py` 命中时不动任何文件 |
| 磁盘不足跳过 | 可用空间小于 2GB 时跳过 |
| 备份方式 | `mv` 到 `~/maaend/backups/<时间戳>/`，备份是完整的一份 |
| 替换范围 | `resource/`、`interface.json`、`tasks/`、`agent/{go-service,cpp-algo}`、`maafw/`，**不碰 `web/`** |
| 自检 | `post_upgrade_check.py` 检查 15 个关键节点，缺一个就回滚 |
| 选项基线 | `option_audit.py` 对照 `option_baseline.json`，漂移写 `~/maaend/option_drift.json`；不升级的日子也会跑 |
| 备份保留 | 最近 4 份，旧的自动清理 |

升级后有两处是**补丁**而不是上游原样：

- `agent/cpp-algo` 固定回 1.0856 版（3.86 units/度）。发行版新版按 7.93 units/度算，会让导航 2 倍超调、永不收敛；补丁按 md5 判断，找不到 `patches/agent/cpp-algo-1.0856.bin` 时保留原文件并在日志里写明。
- `resource/pipeline/nodes.json` 里 `AutoStockpileSelectMarket` 的 `pre_wait_freezes` 从 80 改 160（等上游发版带上后可以删这段）。

升级还会冲掉仓库侧的任务改动与定点修补（发行版整包替换 `tasks/`）。这一层由 `homesrv/overlay_apply.py` 按 `overlay_ops.json` 的声明叠回，幂等，`auto_update.sh` 与 `deploy.sh` 都会调它：

```bash
python3 web/linux/homesrv/overlay_apply.py --root ~/maaend --dry-run   # 只报告会做什么
python3 web/linux/homesrv/overlay_apply.py --root ~/maaend             # 叠回
```

叠回失败不会静默：`auto_update.sh` 会回滚到刚备份的版本、写 `~/maaend/upgrade_alert.txt` 并终端响铃；`nightly_run_homesrv.sh` 开跑时先读这个文件，把失败亮出来。

手工用法与回滚：

```bash
bash web/linux/homesrv/auto_update.sh --check   # 只看当前版本与上游最新版
bash web/linux/homesrv/auto_update.sh --force   # 版本相同也重装一次
```

自动回滚由脚本在自检失败时执行。要手工回到某个备份（与脚本内 `rollback()` 同一顺序）：

```bash
cd "$HOME/maaend"
TS=<backups 下的目录名>
rm -rf resource maafw
mv "backups/$TS/resource" ./resource
mv "backups/$TS/maafw" ./maafw
cp -a "backups/$TS/interface.json" ./interface.json
cp -a "backups/$TS/agent/." ./agent/
ln -sfn "$HOME/maaend/maafw" "$HOME/maaend/agent/maafw"
```

`tasks/` 的备份单独放在 `backups/tasks-prev/`：升级会用发行版覆盖同名任务文件，但不删除本地自建任务。仓库里对 `tasks/` 的修改（服包名、选项树修正）由 `overlay_apply.py` 在升级后叠回，覆盖项清单在 `overlay_ops.json`，映射见 [`project-20261104/PLAN.md`](./project-20261104/PLAN.md)。

> [!WARNING]
> 别在 `web/` 之外改部署机的运行逻辑。`auto_update.sh` 只保护 `web/` 与 `config/`，其他位置的改动会在下次升级时被抹掉。

## 故障恢复

| 现象 | 处理 |
| --- | --- |
| 任务卡住、要人工接管 | `bash web/linux/homesrv/stop_homesrv.sh`，它停 runner → 通知服务端结束会话 → 关进程 → 35 秒后复验 |
| 云会话还在计费 | `python web/linux/leave_game.py --port 9334`，先让页面离开云游戏（省畅玩卡时长） |
| 收尾后仍有残留进程 | 看 `mh_cleanup` 打印的 `chrome= / agent= / sway=` 三个计数，非 0 的那个查 `pgrep -af` |
| 升级后节点大面积不命中 | 看 `~/maaend/upgrade.log` 是否有 `自检未通过，回滚`；再看 `option_drift.json` |
| 选项树漂移 | `python web/linux/homesrv/option_audit.py --check` |
| 回到本轮重构前的代码 | `git checkout <上一个分支> -- web/`（本轮全部改动在 `feat/web-linux-project-20261104`） |

日志位置：运行日志在 `~/maaend/{daily,essence,nightly,upgrade}.log`（各保留最近 3 份，`.1` / `.2` 是旧的一轮），框架日志在 `$MAA_LOG_DIR`（默认 `~/maaend-log`）。失败现场帧只在失败时保留，正常跑完 `vision/` 会被框架清空。
