#!/usr/bin/env bash
# 量一下关键 CDN 的实际下载速度，并试走 Windows 代理（WSL2 网关:7890）。
set -uo pipefail

URL="${1:-https://web.hycdn.cn/hg_account_web_sdk/lib/3.5.0/hg-account-web-sdk.min.js}"
GW=$(python3 - <<'PY'
import socket, struct
best = None
for line in open('/proc/net/route').read().splitlines()[1:]:
    f = line.split()
    if f[1] == '00000000':
        best = socket.inet_ntoa(struct.pack('<L', int(f[2], 16)))
        break
print(best or '')
PY
)

bench() {
  local label="$1"; shift
  printf '%-22s ' "$label"
  curl -s -o /tmp/net_probe.bin -m 30 "$@" -w 'code=%{http_code} size=%{size_download} time=%{time_total}s speed=%{speed_download}B/s\n' "$URL" 2>&1 || echo "失败"
}

echo "网关: ${GW:-未知}"
bench "直连"
[ -n "$GW" ] && bench "Windows 代理($GW:7890)" -x "http://$GW:7890"
echo
echo "文件大小参考: $(curl -sI -m 10 "$URL" | grep -i content-length | tr -d '\r')"
