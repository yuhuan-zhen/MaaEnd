#!/usr/bin/env bash
# homesrv 夜间总调度（cron 03:00 一条）：检查更新 → 日常 10 项 → 基质刷取（多轮重试）。
# 三步串行，避免同时抢同一个 Chrome profile 与 sway 会话。
# 每步 rc 都记录，任一步失败不影响后面（日常挂了基质仍值得试）。
# 本脚本只做串行与汇总：不注册收尾 trap，清理由 daily / essence 各自负责（与重构前一致）。
#
# 失败可见性：cron 里 stderr 被重定向掉，所以任一步失败都会在日志里打 [!] 行并响铃；
# upgrade_alert.txt（auto_update 叠回 tasks/覆盖层失败时写）会在下次开跑时先被亮出来。
#
# 退出码（与重构前一致）：日常或基质任一成功 → 0；两者都失败 → 1。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
. "$HERE/lib.sh"

ROOT="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
LOG="$ROOT/nightly.log"

mh_session            # cron 环境下补齐会话变量
mh_rotate_log "$LOG"  # 只保留最近 3 次运行
: >"$LOG"
exec 3>&2
exec >>"$LOG" 2>&1

echo "===== $(date -Is) 夜间链 开始 ====="

# 上一轮升级/叠回失败留下的告警：先亮出来，也别让它埋在 upgrade.log 里。
# 同一条内容只亮一次（ALERT_SHOWN 记最近一次打印过的正文）。
ALERT_SHOWN=""
show_alert() {
  if [ ! -f "$ROOT/upgrade_alert.txt" ]; then
    return 0
  fi
  local body
  body=$(cat "$ROOT/upgrade_alert.txt" 2>/dev/null || true)
  if [ -z "$body" ] || [ "$body" = "$ALERT_SHOWN" ]; then
    return 0
  fi
  ALERT_SHOWN="$body"
  mh_bell
  echo "[!] 升级告警 $ROOT/upgrade_alert.txt（下次升级+叠回成功会自动清掉）："
  printf '%s\n' "$body" | sed 's/^/[!] /'
  return 0
}

show_alert

# 单步执行：打印开始/结束与 rc，把 rc 原样返回（不改变各子脚本的语义）。
run_step() {
  local idx="$1" name="$2" script="$3" rc=0
  echo
  echo "--- [$idx/3] $name 开始 $(date -Is)"
  bash "$script"
  rc=$?
  echo "--- [$idx/3] $name 结束 rc=$rc $(date -Is)"
  return "$rc"
}

rc1=0
run_step 1 auto_update "$HERE/auto_update.sh"
rc1=$?
# auto_update 的退出码恒 0（设计如此），它的失败只能用告警文件当场暴露。
show_alert
rc2=0
run_step 2 daily "$HERE/daily_run_homesrv.sh"
rc2=$?
rc3=0
run_step 3 essence "$HERE/essence_run_homesrv.sh"
rc3=$?

echo
echo "===== $(date -Is) 夜间链 结束  auto_update=$rc1 daily=$rc2 essence=$rc3 ====="
if [ "$rc1" -ne 0 ] || [ "$rc2" -ne 0 ] || [ "$rc3" -ne 0 ]; then
  mh_bell
  echo "[!] 有步骤失败：auto_update=$rc1 daily=$rc2 essence=$rc3（详见 daily.log / essence.log / upgrade.log）"
fi
# 日常与基质都失败才算整体失败
if [ "$rc2" -eq 0 ] || [ "$rc3" -eq 0 ]; then
  exit 0
fi
exit 1
