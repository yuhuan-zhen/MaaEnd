#!/usr/bin/env bash
# homesrv 夜间总调度（cron 03:00 一条）：更新 → 日常 10 项 → 基质刷取（多轮重试）。
# 三步串行，避免同时抢同一个 Chrome profile 与 sway 会话。
# 每步 rc 都记录，任一步失败不影响后面（日常挂了基质仍值得试）。
# 本脚本只做串行与汇总：不注册收尾 trap，清理由 daily / essence 各自负责（与重构前一致）。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

ROOT="$HOME/maaend"
LOG="$ROOT/nightly.log"

mh_session            # cron 环境下补齐会话变量
mh_rotate_log "$LOG"  # 只保留最近 3 次运行
: >"$LOG"
exec >>"$LOG" 2>&1

echo "===== $(date -Is) 夜间链 开始 ====="

echo
echo "--- [1/3] auto_update 开始 $(date -Is)"
bash "$ROOT/web/linux/homesrv/auto_update.sh"
rc1=$?
echo "--- [1/3] auto_update 结束 rc=$rc1 $(date -Is)"

echo
echo "--- [2/3] daily 开始 $(date -Is)"
bash "$ROOT/web/linux/homesrv/daily_run_homesrv.sh"
rc2=$?
echo "--- [2/3] daily 结束 rc=$rc2 $(date -Is)"

echo
echo "--- [3/3] essence 开始 $(date -Is)"
bash "$ROOT/web/linux/homesrv/essence_run_homesrv.sh"
rc3=$?
echo "--- [3/3] essence 结束 rc=$rc3 $(date -Is)"

echo
echo "===== $(date -Is) 夜间链 结束  auto_update=$rc1 daily=$rc2 essence=$rc3 ====="
# 日常与基质都失败才算整体失败（auto_update 失败也报出来）
if [ "$rc2" -eq 0 ] || [ "$rc3" -eq 0 ]; then
  exit 0
fi
exit 1
