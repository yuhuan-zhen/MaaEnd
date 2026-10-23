#!/usr/bin/env bash
# 出一张能扫的登录二维码：定位页面 → 切到扫码登录 → 截图 → 裁切放大。
#
#   ./show_qr.sh          # 需要时自动起 launcher
#   ./show_qr.sh --fresh  # 先收尾再重起
#
# 产物：
#   D:\桌面\maaend-manual\qr-live.png   整页
#   D:\桌面\maaend-manual\qr-only.png   二维码（3 倍放大，直接用手机扫）
set -uo pipefail

REPO="${REPO:-/mnt/d/maaend-upstream}"
WEB="$REPO/web"
STATE_DIR=/tmp/maaend-manual
LAUNCH_JSON="$STATE_DIR/launch.json"
SHOT_DIR="${SHOT_DIR:-/mnt/d/桌面/maaend-manual}"
PORT="${PORT:-9334}"

mkdir -p "$SHOT_DIR" "$STATE_DIR"

if [ -z "${MAAEND_WEB_PROXY:-}" ]; then
  GW=$(python3 - <<'PY' 2>/dev/null
import socket, struct
for line in open("/proc/net/route").read().splitlines()[1:]:
    f = line.split()
    if f[1] == "00000000":
        print(socket.inet_ntoa(struct.pack("<L", int(f[2], 16))))
        break
PY
)
  [ -n "$GW" ] && MAAEND_WEB_PROXY="http://$GW:7890"
fi
export MAAEND_WEB_PROXY

if [ "${1:-}" = "--fresh" ] || [ ! -s "$LAUNCH_JSON" ]; then
  "$WEB/linux/wsl/grab_qr.sh" --fresh >/dev/null 2>&1 || true
  [ -s "$LAUNCH_JSON" ] || { echo "launcher 没起来，先跑 grab_qr.sh 看日志"; exit 1; }
fi

python3 "$WEB/linux/wsl/qr_helper.py" --json "$LAUNCH_JSON" --out "$SHOT_DIR"
