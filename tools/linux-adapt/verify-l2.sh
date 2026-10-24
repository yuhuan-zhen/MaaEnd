#!/usr/bin/env bash
# L2 验收（工具层）：起 headless sway → 跑 l2_task → 逐项判定
#
# 用法：bash verify-l2.sh
# 判据：退出码 0、资源加载 2 个节点、tasker inited、任务 Succeeded、
#       执行轨迹 2 个节点且都 completed=1
set -uo pipefail

export XDG_RUNTIME_DIR=/run/user/0
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BIN="$HERE/mini-cpp/build/l2_task"
RES="$HERE/mini-cpp/l2-resource"
SOCK=wayland-1
CONF=/tmp/l2sway.conf
SWAY_LOG=/tmp/l2-sway.log

fail=0
pass() { echo "[PASS] $1"; }
bad() { echo "[FAIL] $1"; fail=1; }

command -v sway >/dev/null 2>&1 || { bad "sway 未安装"; exit 1; }
[ -x "$BIN" ] || { bad "未构建：$BIN（先 cmake --build build）"; exit 1; }

printf 'output HEADLESS-1 resolution 1280x720 bg #1b2b34 solid_color\n' > "$CONF"
rm -f "$XDG_RUNTIME_DIR/$SOCK" "$XDG_RUNTIME_DIR/$SOCK.lock" 2>/dev/null

WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 sway -c "$CONF" > "$SWAY_LOG" 2>&1 &
SWAY_PID=$!
trap 'kill "$SWAY_PID" 2>/dev/null' EXIT
sleep 2.5

if [ ! -S "$XDG_RUNTIME_DIR/$SOCK" ]; then
    bad "sway 未起：$XDG_RUNTIME_DIR/$SOCK 不存在"
    tail -5 "$SWAY_LOG"
    exit 1
fi
pass "headless sway 已起（$SOCK）"

OUT=$(cd "$HERE/mini-cpp" && "$BIN" --socket "$SOCK" --resource "$RES" 2>&1)
RC=$?

echo "---- 程序输出（已滤掉 ONNX/WebGPU 噪声）----"
echo "$OUT" | grep -v -E "vkCreateInstance|ONNXResMgr|CheckVkSuccessImpl|^\s*at |^$" | sed 's/^/    /'
echo "---- 判定 ----"

[ "$RC" -eq 0 ] && pass "退出码 0" || bad "退出码 $RC"

grep_q() { echo "$OUT" | grep -q -- "$1"; }
grep_q "resource nodes: 2" && pass "资源加载 2 个节点" || bad "资源节点数不为 2"
grep_q "tasker inited" && pass "tasker inited" || bad "tasker 未 inited"
grep_q "-> Succeeded" && pass "任务 Succeeded" || bad "任务未 Succeeded"
grep_q "executed nodes: 2" && pass "执行轨迹 2 个节点" || bad "执行轨迹节点数不为 2"
grep_q "L2Click .*completed=1" && pass "L2Click completed=1" || bad "L2Click 未完成"
grep_q "L2Done .*completed=1" && pass "L2Done completed=1" || bad "L2Done 未完成"

CTX=$(echo "$OUT" | grep -o "context events: [0-9]*" | tail -1)
echo "[INFO] $CTX（节点级事件经 context sink；为 0 说明该版本不推节点事件）"

if [ "$fail" -eq 0 ]; then
    echo "L2_OK"
else
    echo "L2_FAIL"
fi
exit "$fail"
