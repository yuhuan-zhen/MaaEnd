#!/usr/bin/env bash
# homesrv 版日常：起浏览器 → 按预设跑 → 收尾。
# 收尾规则固定：跑完必须关掉 云·终末地(Chrome) + MaaEnd agent(go-service) + 合成器，只留下 cron 这个定时器本身。
# 会话变量、日志轮转、启动、等 CDP、页面归位、浮层自检、收尾都在 lib.sh（trap 保证失败/中断也照样清理）。
# 本文件只保留 daily 的差异：CONF/LOG、TASKS、INSTANCE、参数拼装、退出码。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

ROOT="$HOME/maaend"
TASKS=""
INSTANCE="hmuddz8"

mh_init "$ROOT" "$ROOT/daily.log"
# daily.conf 是部署机上的运行时配置，仓库里没有；缺失就用上面的默认值
# shellcheck source=/dev/null
if [ -f "$CONF" ]; then
  . "$CONF"
fi
# 便于手动临时覆盖：MAAEND_TASKS=1,2 ./daily_run_homesrv.sh
TASKS="${MAAEND_TASKS:-${TASKS:-}}"

echo
echo "===== $(date -Is) 开始  预设=$INSTANCE 任务=[${TASKS:-全部}] ====="

mh_start_chrome || exit 10
mh_wait_cdp
mh_reset_page

ARGS=(--instance "$INSTANCE")
if [ -n "${TASKS:-}" ]; then
  ARGS+=(--tasks "$TASKS")
fi
python3 -u "$WEB/linux/run_daily_linux.py" "${ARGS[@]}" "$@"
RC=$?

mh_overlay_check

echo "===== $(date -Is) 结束 rc=$RC ====="
exit "$RC"
