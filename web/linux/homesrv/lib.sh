#!/usr/bin/env bash
# homesrv 部署层公共函数：会话变量、资源层、日志轮转、浏览器启动、等 CDP、页面归位、浮层自检、收尾。
#
# 只定义函数（外加记录自身目录 MH_HERE），顶层不做任何动作；由 daily_run_homesrv.sh /
# essence_run_homesrv.sh / nightly_run_homesrv.sh / stop_homesrv.sh source。调用方保留
# set -uo pipefail 与自己的差异（CONF / TASKS / 实例 / 退出码）。
#
# 收尾判据（2026-11-04 核对）：chrome=0 agent=0 sway=0。
#   chrome 按 "user-data-dir=$PROFILE" 计数，不再假设二进制叫 google-chrome —— 生产用的是
#     $HOME/opt/chrome/.../google-chrome 与 MXU 自带的 chrome，旧写法 `google-chrome.*` 会永远数到 0，
#     收尾判定假通过；
#   agent  = go-service + cpp-algo 两个子进程之和；
#   sway   = pgrep -x（进程名精确匹配），不用 "sway -c " 全命令行匹配。
#   有残留：响铃 + 打 [!] 行，且不会改成非 0 退出码（收尾不影响调用方的 rc 语义）。
#
# 退出码（函数级约定）：0 正常；2 用法/配置缺失；10 浏览器启动失败（mh_start_chrome）。

MH_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# cron 环境下补齐会话变量（缺 XDG_RUNTIME_DIR 会让点击不生效）。
# 手动跑时这些变量已在环境里，保持原值不动。
mh_session() {
  if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "/run/user/$(id -u)" ]; then
    XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export XDG_RUNTIME_DIR
  fi
  if [ -z "${XDG_SESSION_TYPE:-}" ]; then
    export XDG_SESSION_TYPE=wayland
  fi
  if [ -S "${XDG_RUNTIME_DIR:-/nonexistent}/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
  fi
  return 0
}

# 日志轮转：只保留最近 3 次运行（xxx.log + .1 + .2）。
mh_rotate_log() {
  local logfile="$1"
  if [ -s "$logfile" ]; then
    rm -f "$logfile.2"
    if [ -f "$logfile.1" ]; then
      mv -f "$logfile.1" "$logfile.2"
    fi
    mv -f "$logfile" "$logfile.1"
  fi
  return 0
}

# 打印到终端（mh_init 之前保存下来的 stderr）并同时留在日志里。
# 用在「必须让人看见」的错误上：mh_init 之后 stdout/stderr 都进了日志，cron 里没人看得到。
mh_err() {
  printf '%s\n' "$*" >&3 2>/dev/null || printf '%s\n' "$*" >&2
  printf '%s\n' "$*"
}

# 响铃：终端一声，日志里留一个 BEL（cron 重定向到文件时至少能在 less/vim 里看见）。
mh_bell() {
  printf '\a' >&3 2>/dev/null || printf '\a' >&2
  printf '\a\n'
  return 0
}

# ---- 进程计数 ----------------------------------------------------------------
# pgrep 在「没匹配」时打印 0 但返回 1，所以统一吞掉返回码、只保留数字。
mh_count_chrome() {
  local n
  n=$(pgrep -fc -- "user-data-dir=$PROFILE" 2>/dev/null) || n=0
  printf '%s' "${n:-0}"
}

mh_count_agent() {
  local a b
  a=$(pgrep -fc -- "$ROOT/agent/go-service" 2>/dev/null) || a=0
  b=$(pgrep -fc -- "$ROOT/agent/cpp-algo" 2>/dev/null) || b=0
  printf '%s' "$(( ${a:-0} + ${b:-0} ))"
}

mh_count_sway() {
  local n
  n=$(pgrep -xc sway 2>/dev/null) || n=0
  printf '%s' "${n:-0}"
}

# 收尾判据的一行输出，daily/essence 的收尾与 stop_homesrv.sh 共用。
mh_report_left() {
  printf 'chrome=%s agent=%s sway=%s\n' \
    "$(mh_count_chrome)" "$(mh_count_agent)" "$(mh_count_sway)"
}

# ---- 资源层 ------------------------------------------------------------------
MH_RES_LAYERS=()

# 按顺序取第一个存在的候选目录；都不存在返回 1（由调用方决定是否告警）。
_mh_add_layer() {
  local cand
  for cand in "$@"; do
    if [ -d "$cand" ]; then
      MH_RES_LAYERS+=("$cand")
      return 0
    fi
  done
  return 1
}

# 资源层（深合并顺序 = 从左到右，后者覆盖前者），对齐 assets/interface.json 里
# Linux-Wlroots 的 attach_resource_path，再加部署机现场的两层：
#   resource（发行版 base）→ resource_cloud（官方云层，新版本才发）→ resource_cloud_web
#   （我们合并后的网页端覆盖层，deploy.sh 铺到根目录）→ web/linux/resource_web_linux（Linux 薄覆盖）。
# 旧布局（web/resource_web + web/resource_web_homesrv）只在新目录不存在时兜底，
# 避免同一批节点被加载两遍。
# 注意：旧版的 resource_cloud_adb 故意不映射 —— 老发行版里它是 ADB 云层，本轮网页端
# 链路从没加载过它，自动接上会改变现有行为。
mh_res_dirs() {
  MH_RES_LAYERS=()
  if ! _mh_add_layer "$ROOT/resource"; then
    printf '[!] 缺少发行版基础资源 %s（升级/部署不完整？）\n' "$ROOT/resource" >&2
  fi
  _mh_add_layer "$ROOT/resource_cloud" || true
  if ! _mh_add_layer "$ROOT/resource_cloud_web"; then
    _mh_add_layer "$ROOT/web/resource_web" || true
    _mh_add_layer "$ROOT/web/resource_web_homesrv" || true
  fi
  _mh_add_layer "$ROOT/web/linux/resource_web_linux" || true
  local IFS=:
  printf '%s' "${MH_RES_LAYERS[*]}"
}

# ---- 收尾 --------------------------------------------------------------------
# 杀掉本会话的 Chrome / agent / 浮层 watch / 合成器；先 TERM，残留再 KILL 一次。
mh_kill_session() {
  pkill -f "run_daily_linux[.]py" 2>/dev/null || true
  pkill -f "$ROOT/agent/go-service" 2>/dev/null || true
  pkill -f "$ROOT/agent/cpp-algo" 2>/dev/null || true
  pkill -f "overlay_ctl.py --watch" 2>/dev/null || true
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true
  sleep 2
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true
  pkill -x swaybg 2>/dev/null || true
  pkill -x sway 2>/dev/null || true
  sleep 1
  if [ "$(mh_count_chrome)" != "0" ] || [ "$(mh_count_agent)" != "0" ]; then
    pkill -9 -f "user-data-dir=$PROFILE" 2>/dev/null || true
    pkill -9 -f "$ROOT/agent/go-service" 2>/dev/null || true
    pkill -9 -f "$ROOT/agent/cpp-algo" 2>/dev/null || true
    sleep 1
  fi
  return 0
}

# 收尾：先通知服务端结束会话，再关 Chrome / agent / 浮层 / 合成器，最后打印三项残留计数。
# mh_init 把它注册到 EXIT（INT/TERM 先 exit，再由 EXIT 统一收尾），失败与中断也照样清理。
# MH_CLEANED 保证只跑一次：否则 INT → EXIT 会把收尾做两遍。
mh_cleanup() {
  if [ "${MH_CLEANED:-0}" = "1" ]; then
    return 0
  fi
  MH_CLEANED=1
  echo "[i] 收尾：先让页面离开云游戏（通知服务端结束会话），再关进程"
  if [ -f "$WEB/linux/leave_game.py" ]; then
    python3 "$WEB/linux/leave_game.py" --port "$CDP_PORT" 2>&1 | tail -2 || true
  fi
  echo "[i] 收尾：关闭 云·终末地 与 MaaEnd 相关进程"
  mh_kill_session
  local left_chrome left_agent left_sway
  left_chrome=$(mh_count_chrome)
  left_agent=$(mh_count_agent)
  left_sway=$(mh_count_sway)
  echo "[i] 残留：chrome=$left_chrome agent=$left_agent sway=$left_sway"
  if [ "$left_chrome" = "0" ] && [ "$left_agent" = "0" ] && [ "$left_sway" = "0" ]; then
    echo "[✓] 收尾干净（chrome=0 agent=0 sway=0）"
  else
    mh_bell
    echo "[!] 收尾仍有残留（chrome=$left_chrome agent=$left_agent sway=$left_sway），见 stop_homesrv.sh"
  fi
  return 0
}

# ---- 启动与页面归位 ----------------------------------------------------------
# 起 sway + Chrome（唯一启动入口是 chrome_homesrv.sh，含视口校验与浮层注入）。
# 失败统一返回 10，调用方用 `mh_start_chrome || exit 10`。
mh_start_chrome() {
  if ! bash "$MH_HERE/chrome_homesrv.sh"; then
    echo "[X] 启动浏览器失败"
    return 10
  fi
  return 0
}

# 等 CDP 端点起来：最多 30 次 × 2s（与重构前一致，超时不报错，交给后面步骤暴露）。
mh_wait_cdp() {
  local i
  for ((i = 1; i <= 30; i++)); do
    if curl -s --max-time 2 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  return 0
}

# 回到启动页并滚到顶，避免上次点击把页面带偏；归位失败不阻塞后续任务。
mh_reset_page() {
  python3 "$WEB/linux/reset_page.py" --port "$CDP_PORT" --url https://endfield.hypergryph.com/cloud --wait 12 2>&1 | tail -2 || true
  return 0
}

# 验证悬浮球与延迟角标是否被隐藏（overlay_ctl.py 在 chrome 启动时注入）。
# --check 的 rc=1 表示「仍有可见浮层」，只记日志不中断（与重构前一致）。
mh_overlay_check() {
  if [ -f "$WEB/linux/overlay_ctl.py" ]; then
    python3 "$WEB/linux/overlay_ctl.py" --check --port "$CDP_PORT" 2>&1 | sed 's/^/[浮层] /' || true
  else
    echo "[浮层] 缺少 $WEB/linux/overlay_ctl.py，跳过自检"
  fi
  return 0
}

# ---- 入口 --------------------------------------------------------------------
# 入口：mh_init <root> <logfile>。
# 推导 WEB / CONF（由 logfile 主名得到，daily.log → daily.conf）/ PROFILE / CDP_PORT，
# 导出 MAAEND_*，轮转日志、接管 stdout/stderr、注册收尾 trap。
# ROOT/WEB/CONF/LOG/PROFILE/CDP_PORT 故意保持全局：脚本主体与子进程都要读。
# 已经显式设置的 MAAEND_RES_DIRS / MAA_AGENT_* / MAAEND_WEB_CDP_PORT 一律尊重（便于排查与灰度）。
mh_init() {
  if [ $# -lt 2 ]; then
    echo "用法: mh_init <root> <logfile>" >&2
    return 2
  fi
  ROOT="$1"
  LOG="$2"
  WEB="$ROOT/web"
  # CONF 供调用方（daily/essence）source，本文件不读它，故此处只看不用
  # shellcheck disable=SC2034
  CONF="${MAAEND_CONF:-$ROOT/$(basename "$LOG" .log).conf}"
  PROFILE="${MAAEND_PROFILE:-$HOME/.config/endfield-web}"
  CDP_PORT="${MAAEND_WEB_CDP_PORT:-9334}"

  mh_session
  export MAAEND_DIST="$ROOT"
  export MAAEND_ROOT="$ROOT"
  export MAAEND_WEB="$WEB"
  export MAAEND_WEB_CDP_PORT="$CDP_PORT"
  export MAAEND_PROFILE="$PROFILE"
  if [ -z "${MAAEND_RES_DIRS:-}" ]; then
    MAAEND_RES_DIRS="$(mh_res_dirs)"
    export MAAEND_RES_DIRS
  fi
  export MAA_AGENT_BIN="${MAA_AGENT_BIN:-$ROOT/agent/go-service}"
  export MAA_AGENT_LIB="${MAA_AGENT_LIB:-$ROOT/maafw}"

  mh_rotate_log "$LOG"
  : >"$LOG"
  exec 3>&2
  exec >>"$LOG" 2>&1
  trap mh_cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  echo "[i] 根目录: $ROOT"
  echo "[i] 资源层: $MAAEND_RES_DIRS"
  echo "[i] CDP: 127.0.0.1:$CDP_PORT  预设配置: $CONF"
  return 0
}
