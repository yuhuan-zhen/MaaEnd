#!/bin/bash
# 停止 homesrv 上正在跑的基质任务并完整收尾（会话/浏览器/合成器/agent）
echo "== 1) 停 runner =="
PIDS=$(pgrep -f "web/linux/run_daily_linux.py")
for p in $PIDS; do kill -TERM "$p" 2>/dev/null && echo "TERM $p"; done
sleep 5
echo "runner_left=$(pgrep -fc 'web/linux/run_daily_linux.py' 2>/dev/null || echo 0)"

echo "== 2) 通知服务端结束会话（省畅玩卡时长）=="
cd "$HOME/maaend/web/linux" 2>/dev/null && timeout 30 python3 leave_game.py --port 9334 2>&1 | tail -2

echo "== 3) 关 agent / 浏览器 / 合成器 =="
pkill -x cpp-algo 2>/dev/null; pkill -x go-service 2>/dev/null
sleep 1
pkill -x chrome 2>/dev/null
sleep 2
pkill -x chrome 2>/dev/null
pkill -x swaybg 2>/dev/null
pkill -x sway 2>/dev/null
sleep 2

echo "== 4) 第一次验收 =="
echo "chrome=$(pgrep -x chrome 2>/dev/null | wc -l) sway=$(pgrep -xc sway 2>/dev/null || echo 0) cpp=$(pgrep -xc cpp-algo 2>/dev/null || echo 0) go=$(pgrep -xc go-service 2>/dev/null || echo 0) runner=$(pgrep -fc 'web/linux/run_daily_linux.py' 2>/dev/null || echo 0)"
sleep 35
echo "== 5) 35 秒后复验（防「杀完又起来」）=="
echo "chrome=$(pgrep -x chrome 2>/dev/null | wc -l) sway=$(pgrep -xc sway 2>/dev/null || echo 0) cpp=$(pgrep -xc cpp-algo 2>/dev/null || echo 0) go=$(pgrep -xc go-service 2>/dev/null || echo 0) runner=$(pgrep -fc 'web/linux/run_daily_linux.py' 2>/dev/null || echo 0)"
ls /run/user/$(id -u)/wayland-* 2>/dev/null | head -3
