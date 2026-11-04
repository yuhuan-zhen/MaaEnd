# 重构前行为基线（2026-11-04）

这些输出是重构验收的黄金基线：重构后同样的命令必须逐字一致（时间戳除外）。

## 环境

homesrv（Ubuntu 24.04，Python 3.12.3），仓库部署在 `~/maaend`，基线与重构前代码同为 `master@4e98104`。

```bash
cd ~/maaend
export MAAEND_ROOT=$HOME/maaend MAAEND_DIST=$HOME/maaend MAAEND_WEB=$HOME/maaend/web
export MAAEND_RES_DIRS=$HOME/maaend/resource:$HOME/maaend/web/resource_web:$HOME/maaend/web/linux/resource_web_linux:$HOME/maaend/web/resource_web_homesrv
python3 web/linux/run_daily_linux.py --instance hmuddz8 --dry-run
python3 web/linux/run_daily_linux.py --instance hyasuml --dry-run
```

原始输出：`dryrun-baseline-20261104.txt`。

## hmuddz8（快速日常）

```text
待跑 11 项: WebStartGame/VisitFriends/DijiangRewards/CreditShoppingN2/DeliveryJobs/AutoStockpile/AutoSell/AutoStockStaple/SellProduct/DailyRewards/AutoEssence
   1. WebStartGame           -> WebStartGameEntry                覆盖 0 项
   2. VisitFriends           -> VisitFriendsMain                 覆盖 15 项
   3. DijiangRewards         -> DijiangRewards                   覆盖 25 项
   4. CreditShoppingN2       -> CreditShoppingMain               覆盖 37 项
   5. DeliveryJobs           -> DeliveryJobsMain                 覆盖 19 项
   6. AutoStockpile          -> AutoStockpileMain                覆盖 5 项
   7. AutoSell               -> AutoSellMain                     覆盖 6 项
   8. AutoStockStaple        -> AutoStockStapleSchedule          覆盖 107 项
   9. SellProduct            -> OutpostTradingSchedule           覆盖 17 项
  10. DailyRewards           -> DailyRewardStart                 覆盖 15 项
  11. AutoEssence            -> AutoEssenceSchedule              覆盖 21 项
```

## hyasuml（网页端日常全套）

```text
待跑 14 项: WebStartGame/VisitFriends/DijiangRewards/CreditShoppingN2/DeliveryJobs/SellProduct/AutoStockpile/AutoStockStaple/AutoSell/EnvironmentMonitoring/DailyRewards/SeizeDeliveryJobs/ProtocolSpace/AutoCollect
   1. WebStartGame           -> WebStartGameEntry                覆盖 0 项
   2. VisitFriends           -> VisitFriendsMain                 覆盖 15 项
   3. DijiangRewards         -> DijiangRewards                   覆盖 25 项
   4. CreditShoppingN2       -> CreditShoppingMain               覆盖 38 项
   5. DeliveryJobs           -> DeliveryJobsMain                 覆盖 19 项
   6. SellProduct            -> OutpostTradingSchedule           覆盖 17 项
   7. AutoStockpile          -> AutoStockpileMain                覆盖 5 项
   8. AutoStockStaple        -> AutoStockStapleSchedule          覆盖 104 项
   9. AutoSell               -> AutoSellMain                     覆盖 6 项
  10. EnvironmentMonitoring  -> EnvironmentMonitoringMain        覆盖 0 项
  11. DailyRewards           -> DailyRewardStart                 覆盖 10 项
  12. SeizeDeliveryJobs      -> SeizeDeliveryJobsCheckOngoingJob 覆盖 8 项
  13. ProtocolSpace          -> ProtocolSpaceSchedule            覆盖 21 项
  14. AutoCollect            -> AutoCollectSchedule              覆盖 87 项
```

## 复现时注意

- 不导出 `MAAEND_ROOT` 时，旧 `resolve_preset.py` 会回退到 Windows 路径 `D:\jiaoben\MaaEnd-win-x86_64-v2.3.0`，在 homesrv 上直接 `FileNotFoundError`。生产靠 `daily_run_homesrv.sh` 导出环境变量。重构后的 `load_settings()` 默认值改为 `~/maaend`，单独跑不再需要先 source。
- `ensure_preload()` 会 `execv` 自重入一次，日志里出现「为 relative_move/scroll 预加载控制单元」是正常现象。
