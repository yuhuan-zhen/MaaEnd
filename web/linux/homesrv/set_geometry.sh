#!/usr/bin/env bash
# 生产几何一键切换（可回档）。
#   ./set_geometry.sh 720p    1280x720 / DSF 1  / 窗口 1280,720   （省 CPU，生产用）
#   ./set_geometry.sh 1440p   2560x1440 / DSF 1.5 / 窗口 1706,960  （回档到旧生产几何）
#   ./set_geometry.sh show    只打印当前
# 改完在下一次启动浏览器时生效（cron 的 daily_run_homesrv.sh 也读这份 conf）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$HERE/geometry.conf"
case "${1:-show}" in
  720p)  printf 'MAAEND_RES=1280x720\nMAAEND_DSF=1\nMAAEND_WIN=1280,720\n' >"$CONF" ;;
  1440p) printf 'MAAEND_RES=2560x1440\nMAAEND_DSF=1.5\nMAAEND_WIN=1706,960\n' >"$CONF" ;;
  show)  ;;
  *) echo "用法: $0 [720p|1440p|show]" >&2; exit 2 ;;
esac
echo "geometry.conf:"; cat "$CONF" 2>/dev/null || echo "(不存在，脚本将用内置默认 2560x1440)"
