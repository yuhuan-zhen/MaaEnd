#!/usr/bin/env bash
# L1 肉眼验收：抓两帧（换背景色），验证通道序、时效性、耗时。
#
# 用法：
#   bash verify-l1.sh            # 跑完就退
#   bash verify-l1.sh --pause    # 每步停 3 秒，方便肉眼看窗口变化
#
# 产物：evidence-l1/f1-dark.png（#1b2b34）、f2-red.png（#c81e1e）、f3-timing.png
# 依赖：嵌套 sway 跑在 /run/user/0/wayland-1

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/mini-cpp/build/l1_screencap"
SOCKET="${SOCKET:-/run/user/0/wayland-1}"
OUT_DIR="$HERE/evidence-l1"
SWAY_CONF="/tmp/l1-sway.conf"
PAUSE=0
[ "${1:-}" = "--pause" ] && PAUSE=3

fail=0

if [ ! -x "$BIN" ]; then
    echo "找不到 $BIN"
    echo "先编译：cd \"$HERE/mini-cpp\" && cmake -S . -B build -G Ninja && cmake --build build"
    exit 9
fi

mkdir -p "$OUT_DIR"
export XDG_RUNTIME_DIR=/run/user/0

start_sway() {
    local color="$1"
    printf 'output * bg %s solid_color\n' "$color" > "$SWAY_CONF"
    pkill -x swaybg 2>/dev/null
    pkill -x sway 2>/dev/null
    sleep 1
    WAYLAND_DISPLAY=wayland-0 WLR_BACKENDS=wayland WLR_LIBINPUT_NO_DEVICES=1 \
        setsid sway -c "$SWAY_CONF" >> /tmp/l1-sway.log 2>&1 < /dev/null &
    sleep 4
    # swaymsg 靠 SWAYSOCK 找 IPC，sway 只把这条路径写进自己的环境，
    # 不会导出到我们的 shell —— 必须自己从 /run/user/0 里挑。
    SWAYSOCK="$(ls /run/user/0/sway-ipc.* 2>/dev/null | head -1)"
    export SWAYSOCK
}

# 改背景色；失败必须显式报出来，不能像上一版那样把 stderr 丢掉假装成功。
set_bg() {
    local color="$1"
    if ! swaymsg output "*" bg "$color" solid_color >/dev/null; then
        echo "FAIL  改背景色失败：$color（SWAYSOCK=${SWAYSOCK:-未设置}）"
        fail=1
        return 1
    fi
    echo "     背景已改为 $color"
}

check() {
    local label="$1" got="$2" want="$3"
    if [ "$got" = "$want" ]; then
        printf 'PASS  %-38s %s\n' "$label" "$got"
    else
        printf 'FAIL  %-38s 期望 %s，实际 %s\n' "$label" "$want" "$got"
        fail=1
    fi
}

echo "════════════════════════════════════════════════════════════════"
echo "步骤 1：背景 #1b2b34（深蓝灰），抓一帧"
echo "════════════════════════════════════════════════════════════════"
start_sway "#1b2b34"
[ "$PAUSE" -gt 0 ] && sleep "$PAUSE"
out1=$("$BIN" "$SOCKET" --out "$OUT_DIR/f1-dark.png" --frames 20)
echo "$out1"
mean1=$(printf '%s\n' "$out1" | sed -n 's/.*channel mean BGR = \[\([0-9.]*\), \([0-9.]*\), \([0-9.]*\)\].*/\1 \2 \3/p')
median1=$(printf '%s\n' "$out1" | sed -n 's/.*median = \([0-9.]*\).*/\1/p')

echo
echo "════════════════════════════════════════════════════════════════"
echo "步骤 2：背景换成 #c81e1e（红），再抓一帧 —— 证明抓的是实时帧"
echo "════════════════════════════════════════════════════════════════"
set_bg "#c81e1e"
[ "$PAUSE" -gt 0 ] && sleep "$PAUSE"
out2=$("$BIN" "$SOCKET" --out "$OUT_DIR/f2-red.png" --frames 3)
echo "$out2"
mean2=$(printf '%s\n' "$out2" | sed -n 's/.*channel mean BGR = \[\([0-9.]*\), \([0-9.]*\), \([0-9.]*\)\].*/\1 \2 \3/p')

echo
echo "════════════════════════════════════════════════════════════════"
echo "判读"
echo "════════════════════════════════════════════════════════════════"
check "帧 1 均值（#1b2b34 → BGR）" "$mean1" "52.000000 43.000000 27.000000"
check "帧 2 均值（#c81e1e → BGR）" "$mean2" "30.000000 30.000000 200.000000"
printf '%s\n' "$out1" | grep -q "frame = 1280x720, channels = 3, type = 16" \
    && printf 'PASS  %-38s %s\n' "形状 1280x720 / 3ch / type16" "见上" \
    || { printf 'FAIL  %-38s\n' "形状不对"; fail=1; }
printf '%s\n' "$out1" | grep -q "resolution = 1280x720" \
    && printf 'PASS  %-38s %s\n' "截图后 GetResolution" "1280x720" \
    || { printf 'FAIL  %-38s\n' "GetResolution 没给值"; fail=1; }
awk -v m="${median1:-999}" 'BEGIN { exit !(m > 5 && m < 60) }' \
    && printf 'PASS  %-38s %s ms（docs/05 参考 16.2）\n' "median 在合理区间" "$median1" \
    || { printf 'FAIL  %-38s %s ms\n' "median 超出 5–60 ms" "$median1"; fail=1; }

echo
echo "产物："
ls -l "$OUT_DIR"/f1-dark.png "$OUT_DIR"/f2-red.png 2>/dev/null | sed 's/^/  /'

echo
if [ "$fail" -eq 0 ]; then
    echo "结论：全部 PASS"
else
    echo "结论：有 FAIL，见上"
fi
exit "$fail"
