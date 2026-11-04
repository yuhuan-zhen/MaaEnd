#!/usr/bin/env bash
# 停止 homesrv 上正在跑的基质任务并完整收尾（runner / 会话 / 浏览器 / 合成器 / agent）。
# 判据：chrome=0 agent=0 sway=0（与 lib.sh 的 mh_cleanup 同一套计数）；
# 35 秒后复验一次，防「杀完又自己起来」。
#
# 用法：./stop_homesrv.sh
# 退出码：0 收尾干净；1 仍有残留（35 秒复验后）。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
. "$HERE/lib.sh"

ROOT="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
WEB="$ROOT/web"
PROFILE="${MAAEND_PROFILE:-$HOME/.config/endfield-web}"
CDP_PORT="${MAAEND_WEB_CDP_PORT:-9334}"

mh_session
export MAAEND_DIST="$ROOT"
export MAAEND_WEB="$WEB"
export MAAEND_WEB_CDP_PORT="$CDP_PORT"
export MAAEND_PROFILE="$PROFILE"

echo "== 1) 停 runner =="
while IFS= read -r p; do
  [ -n "$p" ] || continue
  if kill -TERM "$p" 2>/dev/null; then
    echo "TERM $p"
  fi
done < <(pgrep -f "web/linux/run_daily_linux[.]py" 2>/dev/null || true)
sleep 5
RUNNER_LEFT=$(pgrep -fc -- "web/linux/run_daily_linux[.]py" 2>/dev/null) || RUNNER_LEFT=0
echo "runner_left=${RUNNER_LEFT:-0}"

echo "== 2) 通知服务端结束会话（省畅玩卡时长）=="
if [ -f "$WEB/linux/leave_game.py" ]; then
  timeout 30 python3 "$WEB/linux/leave_game.py" --port "$CDP_PORT" 2>&1 | tail -2 || true
else
  echo "(缺 $WEB/linux/leave_game.py，跳过)"
fi

echo "== 3) 关 agent / 浏览器 / 合成器 =="
mh_kill_session

echo "== 4) 第一次验收 =="
mh_report_left
sleep 35
echo "== 5) 35 秒后复验（防「杀完又起来」）=="
mh_report_left

find "/run/user/$(id -u)" -maxdepth 1 -name 'wayland-*' 2>/dev/null | head -3 || true

if [ "$(mh_count_chrome)" = "0" ] && [ "$(mh_count_agent)" = "0" ] && [ "$(mh_count_sway)" = "0" ]; then
  echo "[✓] 收尾干净（chrome=0 agent=0 sway=0）"
  exit 0
fi
mh_bell
echo "[!] 仍有残留，见上面的计数；手动看 pgrep -af 相关进程"
exit 1
