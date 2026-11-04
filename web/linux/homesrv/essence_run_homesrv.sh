#!/usr/bin/env bash
# homesrv 版基质刷取（独立链）：起浏览器 → 最多 MAX_ATTEMPTS 轮 WebStartGame+AutoEssence → 收尾。
# 目标：成功 TARGET_OK 轮即停（默认 4），失败继续重试，总尝试上限 MAX_ATTEMPTS（默认 6）。
# 公共层（会话变量/资源层/日志轮转/启动/等 CDP/归位/浮层/收尾）在 lib.sh；
# 本文件只保留 essence 的差异：多轮重试与退出码语义。
#
# 环境变量：MAAEND_ESSENCE_OK / MAAEND_ESSENCE_MAX / MAAEND_ESSENCE_SLEEP 临时覆盖；
#           MAAEND_INSTANCE 覆盖预设；MAAEND_TASKS 覆盖任务串。
# 部署目录：MAAEND_DIST → MAAEND_ROOT → ~/maaend。
#
# 退出码：0 达标（或至少 1 轮成功）；2 缺预设实例；10 浏览器启动失败；否则沿用最后一轮的 rc。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib.sh
. "$HERE/lib.sh"

ROOT="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
TASKS="WebStartGame,AutoEssence"
INSTANCE=""
TARGET_OK="${MAAEND_ESSENCE_OK:-4}"
MAX_ATTEMPTS="${MAAEND_ESSENCE_MAX:-6}"
RETRY_SLEEP="${MAAEND_ESSENCE_SLEEP:-20}"

mh_init "$ROOT" "$ROOT/essence.log"
# essence.conf 是部署机上的运行时配置，仓库里没有；缺失就用环境变量或上面的默认。
# shellcheck source=/dev/null
if [ -f "$CONF" ]; then
  . "$CONF"
fi
INSTANCE="${MAAEND_INSTANCE:-${INSTANCE:-}}"
TASKS="${MAAEND_TASKS:-${TASKS:-}}"

if [ -z "$INSTANCE" ]; then
  mh_err "[X] 没有预设实例：在 $CONF 里写 INSTANCE=<预设 id>，或设 MAAEND_INSTANCE"
  mh_bell
  exit 2
fi

echo
echo "===== $(date -Is) 开始  预设=$INSTANCE 任务=[${TASKS:-全部}] 目标成功=$TARGET_OK 上限=$MAX_ATTEMPTS ====="

mh_start_chrome || exit 10
mh_wait_cdp
mh_reset_page

ok=0
n=0
rc_last=0
while [ "$n" -lt "$MAX_ATTEMPTS" ] && [ "$ok" -lt "$TARGET_OK" ]; do
  n=$((n + 1))
  echo
  echo "----- 第 $n/$MAX_ATTEMPTS 轮 开始 $(date -Is) -----"
  start_line=$(wc -l <"$LOG")
  python3 -u "$WEB/linux/run_daily_linux.py" --instance "$INSTANCE" --tasks "$TASKS" --attempts 1 "$@"
  rc_last=$?
  # 只看本轮新写入的行，避免把上一轮 AutoEssence 的 OK 误算进来
  res=$(tail -n +"$((start_line + 1))" "$LOG" | grep -a "AutoEssence .* OK \|AutoEssence .* FAIL " | tail -1)
  echo "----- 第 $n 轮 结束 $(date -Is) rc=$rc_last 结果: ${res:-未产出} -----"
  case "$res" in
    *" OK "*) ok=$((ok + 1)) ;;
  esac
  if [ "$ok" -ge "$TARGET_OK" ]; then
    break
  fi
  if [ "$n" -lt "$MAX_ATTEMPTS" ]; then
    sleep "$RETRY_SLEEP"
  fi
done

echo
echo "===== 汇总：成功 $ok 轮 / 尝试 $n 轮（目标 $TARGET_OK，上限 $MAX_ATTEMPTS）$(date -Is) ====="

mh_overlay_check

if [ "$ok" -ge "$TARGET_OK" ]; then
  exit 0
fi
# 没达到目标：至少 1 轮成功算部分完成，否则沿用最后一轮的退出码
if [ "$ok" -ge 1 ]; then
  exit 0
fi
exit "${rc_last:-1}"
