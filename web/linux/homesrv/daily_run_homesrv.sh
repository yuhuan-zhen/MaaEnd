#!/usr/bin/env bash
# homesrv 版日常：起浏览器 → 按预设跑 → 收尾。
# 收尾规则固定：跑完必须关掉 云·终末地(Chrome) + MaaEnd agent(go-service/cpp-algo) + 合成器，
# 只留下 cron 这个定时器本身；判据 chrome=0 agent=0 sway=0（lib.sh 的 mh_cleanup 逐项核对）。
# 会话变量、资源层、日志轮转、启动、等 CDP、页面归位、浮层自检、收尾都在 lib.sh
# （trap 保证失败/中断也照样清理）。本文件只保留 daily 的差异：CONF/LOG、TASKS、INSTANCE、退出码。
#
# 部署目录：MAAEND_DIST → MAAEND_ROOT → ~/maaend（与 maaend_web/config.py 的优先级一致）。
# 预设实例：$CONF 里的 INSTANCE，或 MAAEND_INSTANCE；两处都没有就报错退出
# （不再把某台机器的预设 id 写死在脚本里）。
#
# 退出码：0 成功；2 缺预设实例；10 浏览器启动失败；其余沿用 run_daily_linux.py。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
. "$HERE/lib.sh"

ROOT="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
TASKS=""
INSTANCE=""

mh_init "$ROOT" "$ROOT/daily.log"
# daily.conf 是部署机上的运行时配置，仓库里没有；缺失就用环境变量或下面的默认。
# shellcheck source=/dev/null
if [ -f "$CONF" ]; then
  . "$CONF"
fi
# 便于手动临时覆盖：MAAEND_TASKS=1,2 MAAEND_INSTANCE=xxx ./daily_run_homesrv.sh
INSTANCE="${MAAEND_INSTANCE:-${INSTANCE:-}}"
TASKS="${MAAEND_TASKS:-${TASKS:-}}"

if [ -z "$INSTANCE" ]; then
  mh_err "[X] 没有预设实例：在 $CONF 里写 INSTANCE=<预设 id>，或设 MAAEND_INSTANCE"
  mh_bell
  exit 2
fi

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
