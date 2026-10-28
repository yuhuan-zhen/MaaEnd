#!/usr/bin/env bash
# 起浏览器并抓一张当前页面截图（用于扫码登录）。
#   ./grab_qr.sh            # 起/复用 launcher，截图到 D:\桌面\maaend-manual\qr-live.png
#   ./grab_qr.sh --fresh    # 先收尾再重起（换 profile 之外的场景才需要）
set -uo pipefail

REPO="${REPO:-/mnt/d/maaend-upstream}"
WEB="$REPO/web"
LAUNCHER="${LAUNCHER:-/mnt/d/UserDocuments/MaaEnd-review/launcher-draft/cloud-web-launch/cloud-web-launch-linux}"
STATE_DIR=/tmp/maaend-manual
LAUNCH_JSON="$STATE_DIR/launch.json"
SHOT="${SHOT:-/mnt/d/桌面/maaend-manual/qr-live.png}"
URL="${URL:-https://endfield.hypergryph.com/cloud}"
PORT="${PORT:-9334}"

mkdir -p "$STATE_DIR" "$(dirname "$SHOT")"

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

if [ "${1:-}" = "--fresh" ]; then
  "$WEB/linux/wsl/manual_test.sh" stop >/dev/null 2>&1 || true
  pkill -x sway 2>/dev/null || true
  sleep 1
  rm -f "$LAUNCH_JSON"
fi

if [ ! -s "$LAUNCH_JSON" ]; then
  echo "[1/3] 起 launcher（compositor, port=$PORT）"
  setsid "$LAUNCHER" --prepare --mode compositor --cdp-port "$PORT" \
      --profile "$STATE_DIR/profile" --url "$URL" \
      > "$LAUNCH_JSON" 2> "$STATE_DIR/launcher.log" < /dev/null &
  for _ in $(seq 1 60); do [ -s "$LAUNCH_JSON" ] && break; sleep 1; done
  [ -s "$LAUNCH_JSON" ] || { echo "launcher 没起来，看 $STATE_DIR/launcher.log"; exit 1; }
else
  echo "[1/3] 复用已在跑的 launcher"
fi
cat "$LAUNCH_JSON"; echo

echo "[2/3] 等页面渲染"
sleep 12

echo "[3/3] 截图"
python3 "$WEB/linux/wsl/attach_probe.py" --json "$LAUNCH_JSON" --shot "$SHOT" >/dev/null
ls -la "$SHOT"
python3 - "$SHOT" <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1])
print("尺寸:", im.size, "| 非空像素比例:", end=" ")
px = im.convert("L").getdata()
n = sum(1 for p in px if p > 40)
print("%.1f%%" % (100.0 * n / len(px)))
PY
