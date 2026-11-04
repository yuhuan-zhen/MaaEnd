#!/usr/bin/env bash
# 一键部署 homesrv 网页端运行层：备份 → 同步 → 语法检查 → 叠回覆盖层 → dry-run 自检 → 打印回滚。
#
# 只同步仓库自己拥有的东西（web/ 与 assets/resource_cloud_web*），不碰发行版的
# resource/ interface.json agent/ maafw/ —— 那几样由 auto_update.sh 负责。
#
# 用法：
#   ./deploy.sh                              本地部署：源码=本仓库，目标=$MAAEND_DIST 或 ~/maaend
#   ./deploy.sh --dry-run                    只打印计划 + 只读预检，不写任何文件
#   ./deploy.sh --remote homesrv             从 Windows/WSL 推到 homesrv 再在远端执行（tar over ssh）
#   ./deploy.sh --remote homesrv --dry-run   远端只读预检（看目录/磁盘/进程/cron，不传文件）
#   ./deploy.sh --dest ~/maaend-test         换目标（灰度/演练）
#
# 选项：
#   --src DIR      仓库根（默认：本脚本往上三级，web/linux/homesrv → 仓库根）
#   --dest DIR     部署目录（默认 $MAAEND_DIST → $MAAEND_ROOT → ~/maaend）
#   --remote HOST  远端模式：tar 推送 web/ assets/ 到 HOST 的临时目录，再在那边跑本脚本
#   --dry-run      只读：打印计划、跑预检，不备份/不同步/不写文件
#   --yes          不询问（双击/无人值守）；非 tty 下必须给
#   --keep N       部署备份保留份数，默认 4
#   --no-selfcheck 跳过部署后的 run_daily --dry-run 行为自检（不推荐）
#
# 退出码：0 成功；1 用户取消；2 用法错误；3 预检失败；4 备份失败；5 同步失败；
#         6 部署后检查失败（语法/import/覆盖层）；7 行为自检失败。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SRC=""
DEST=""
DEST_EXPLICIT=0
REMOTE=""
DRY=0
YES=0
KEEP=4
SELFCHECK=1

log() { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy][!] %s\n' "$*" >&2; }
die() { printf '[deploy][X] %s\n' "$1" >&2; exit "${2:-3}"; }

# 绝对路径；在 git-bash（MSYS）里优先给 Windows 形式（D:/x），否则 Windows 版 python/node
# 读不了 /d/x 这种路径。Linux 上 `pwd -W` 不存在，自动回落到 `pwd`。
abs_path() {
  ( cd "$1" 2>/dev/null && { pwd -W 2>/dev/null || pwd; } )
}

usage() {
  printf '%s\n' \
    "用法: deploy.sh [--src DIR] [--dest DIR] [--remote HOST] [--dry-run] [--yes] [--keep N] [--no-selfcheck]" \
    "  --dry-run  只读预检：不备份、不同步、不写任何文件" \
    "  --remote   先 tar 推送源码到 HOST，再在 HOST 上执行本脚本" \
    "退出码: 0 成功; 1 取消; 2 用法; 3 预检; 4 备份; 5 同步; 6 部署后检查; 7 行为自检"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="${2:-}"; shift 2 ;;
    --dest) DEST="${2:-}"; DEST_EXPLICIT=1; shift 2 ;;
    --remote) REMOTE="${2:-}"; shift 2 ;;
    --keep) KEEP="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --yes|-y) YES=1; shift ;;
    --no-selfcheck) SELFCHECK=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "未知参数: $1" 2 ;;
  esac
done

if [ -z "$SRC" ]; then
  SRC="$(abs_path "$HERE/../../..")"
fi
if [ ! -d "$SRC" ]; then
  die "源码目录不存在: $SRC" 2
fi
SRC="$(abs_path "$SRC")"
if [ -z "$SRC" ]; then
  die "无法解析源码目录" 2
fi

if [ -z "$DEST" ]; then
  DEST="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
fi
if [ -d "$DEST" ]; then
  DEST="$(abs_path "$DEST")"
fi

case "$KEEP" in
  ''|*[!0-9]*) die "--keep 需要正整数: $KEEP" 2 ;;
esac

# ---- 远端模式 ----------------------------------------------------------------
# 远端只读预检：只用 ls/df/pgrep/crontab，不写远端文件。
# 目标目录默认由**远端**自己算（$MAAEND_DIST → $MAAEND_ROOT → ~/maaend），
# 不能拿本地 $HOME 去拼——Windows 上的 /c/Users/... 在 homesrv 上不存在。
remote_preflight() {
  local host="$1"
  log "远端只读预检 $host（目标目录由远端解析）"
  ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" bash -s <<'REMOTE'
set -u
D="${MAAEND_DIST:-${MAAEND_ROOT:-$HOME/maaend}}"
echo "[remote] host=$(hostname) dest=$D"
if [ -d "$D" ]; then echo "[remote] 部署目录存在"; else echo "[remote][X] 部署目录不存在"; exit 3; fi
if [ -f "$D/interface.json" ]; then echo "[remote] interface.json 在"; else echo "[remote][!] 缺 interface.json（不是完整安装？）"; fi
df -Pk "$D" | awk 'NR==2{printf "[remote] 可用 %s KB\n", $4}'
if pgrep -f "run_daily_linux[.]py" >/dev/null 2>&1; then
  echo "[remote][!] 有任务在跑（真部署会中止）"
else
  echo "[remote] 无任务在跑"
fi
if crontab -l 2>/dev/null | grep -Fq nightly_run_homesrv.sh; then
  echo "[remote] crontab 已挂夜间链"
else
  echo "[remote][!] crontab 里没有 nightly_run_homesrv.sh"
fi
REMOTE
}

remote_deploy() {
  local host="$1" stage rc files dest_args=()
  if [ "$DEST_EXPLICIT" = "1" ]; then
    dest_args=(--dest "$DEST")
  fi
  log "远端部署 $host（tar over ssh，不依赖 rsync）"
  stage=$(ssh -o ConnectTimeout=15 -o BatchMode=yes "$host" mktemp -d /tmp/maaend-deploy-XXXXXX) || die "远端建临时目录失败" 5
  log "暂存目录: $stage"

  files=(web)
  if [ -d "$SRC/assets" ]; then
    files+=(assets)
  fi
  if ! tar -C "$SRC" -cf - "${files[@]}" 2>/dev/null | ssh -o BatchMode=yes "$host" tar -C "$stage" -xf -; then
    ssh -o BatchMode=yes "$host" rm -rf "$stage" 2>/dev/null || true
    die "推送源码失败" 5
  fi

  # 远端用自己的 bash 跑同一份 deploy.sh：源=暂存目录，目标=远端默认为 ~/maaend
  ssh -o BatchMode=yes "$host" bash "$stage/web/linux/homesrv/deploy.sh" \
    --src "$stage" --yes --keep "$KEEP" "${dest_args[@]}"
  rc=$?
  ssh -o BatchMode=yes "$host" rm -rf "$stage" 2>/dev/null || true
  log "远端暂存目录已清理"
  return "$rc"
}

if [ -n "$REMOTE" ]; then
  if [ "$DRY" = "1" ]; then
    remote_preflight "$REMOTE"
    rc=$?
    log "dry-run：远端只做了只读预检，未推送文件、未改任何文件"
    log "真跑：bash $0 --remote $REMOTE --yes"
    exit "$rc"
  fi
  if [ "$YES" != "1" ] && [ ! -t 0 ]; then
    die "非交互环境请加 --yes" 2
  fi
  remote_deploy "$REMOTE"
  exit $?
fi

# ---- 预检 --------------------------------------------------------------------
# 源侧：必需文件、bash 语法、Python 语法、CRLF、覆盖层清单。
preflight_src() {
  local f bad=0 tmp
  log "预检源码 $SRC"
  for f in web/linux/homesrv/lib.sh web/linux/run_daily_linux.py; do
    [ -e "$SRC/$f" ] || die "缺 $SRC/$f（源码不完整）" 3
  done
  [ -e "$SRC/web/linux/overlay_ctl.py" ] || warn "缺 web/linux/overlay_ctl.py，浮层注入会跳过"
  [ -f "$SRC/web/linux/homesrv/overlay_apply.py" ] || die "缺 overlay_apply.py（升级后无法叠回覆盖层）" 3
  [ -f "$SRC/web/linux/homesrv/overlay_ops.json" ] || die "缺 overlay_ops.json" 3

  for f in "$SRC"/web/linux/homesrv/*.sh; do
    [ -e "$f" ] || continue
    if ! bash -n "$f"; then
      bad=1
      warn "bash -n 失败: $f"
    fi
  done
  [ "$bad" = "0" ] || die "shell 语法检查未通过" 3

  # 清单里点名要叠回的任务文件必须在仓库里（否则部署完才发现 import 指向不存在的文件）
  if ! python3 - "$SRC" <<'PY'
import json
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
ops = json.loads((src / "web/linux/homesrv/overlay_ops.json").read_text(encoding="utf-8-sig"))
cfg = ops.get("tasks") or {}
base = src / (cfg.get("stage_from") or "assets/tasks")
missing = [r for r in (cfg.get("include") or []) if not (base / r).is_file()]
print("[deploy] 叠回清单 include 检查: %s" % ("OK" if not missing else ", ".join(missing)))
raise SystemExit(1 if missing else 0)
PY
  then
    die "overlay_ops.json 里 include 点名的任务文件在仓库里找不到" 3
  fi

  tmp=$(mktemp -d "${TMPDIR:-/tmp}/maaend-deploy-check-XXXXXX")
  for f in "$SRC"/web/linux/homesrv/*.py; do
    [ -e "$f" ] || continue
    if ! PYTHONPYCACHEPREFIX="$tmp" python3 -m py_compile "$f"; then
      rm -rf "$tmp"
      die "python 编译失败: $f" 3
    fi
  done
  rm -rf "$tmp"

  # 已知故障史：CRLF 让 bash 报 set: pipefail\r，或让视口校验永远不相等。
  # 逐个文件 grep -q：MSYS 的 grep 在多文件 -l + D:/ 前缀路径的组合下会把所有文件都当命中。
  bad=""
  for f in "$SRC"/web/linux/homesrv/*.sh "$SRC"/web/linux/homesrv/*.py \
           "$SRC"/web/linux/homesrv/geometry.conf "$SRC"/web/linux/homesrv/cloud_policy_linux.js; do
    [ -e "$f" ] || continue
    if grep -q $'\r' "$f" 2>/dev/null; then
      bad="${bad}${f}"$'\n'
    fi
  done
  if [ -n "$bad" ]; then
    printf '%s' "$bad"
    die "上面这些文件是 CRLF，必须先转 LF" 3
  fi
  log "源码预检通过（bash -n / py_compile / LF / 覆盖层清单）"
}

# 目标侧：只读检查（dry-run 也跑，不写）。
preflight_dest() {
  log "预检目标 $DEST"
  if [ ! -d "$DEST" ]; then
    die "部署目录不存在: $DEST（先装一次发行版）" 3
  fi
  [ -f "$DEST/interface.json" ] || warn "缺 $DEST/interface.json（不是完整 MaaEnd 安装？）"
  [ -d "$DEST/resource" ] || warn "缺 $DEST/resource（发行版资源不在，跑不起来）"
  [ -d "$DEST/web" ] || warn "缺 $DEST/web（首次部署？会整目录新建）"
  [ -w "$DEST" ] || die "没有写权限: $DEST" 3
  local free_kb
  free_kb=$(df -Pk "$DEST" 2>/dev/null | awk 'NR==2{print $4}')
  case "${free_kb:-}" in
    ''|*[!0-9]*) warn "读不到 $DEST 的可用空间，跳过磁盘检查" ;;
    *) [ "$free_kb" -ge 1048576 ] || die "磁盘不足 1GB（${free_kb}KB）" 3 ;;
  esac
  if pgrep -f "run_daily_linux[.]py" >/dev/null 2>&1; then
    die "有任务在跑：先 $HERE/stop_homesrv.sh 再部署" 3
  fi
  if ! command -v rsync >/dev/null 2>&1; then
    warn "没有 rsync：退化为 tar 覆盖（不会删除多余文件）"
  fi
}

preflight_src
if [ "$DRY" = "0" ]; then
  preflight_dest
else
  # dry-run 也要把目标状态看清楚，但不做写权限/磁盘门槛的强校验
  if [ -d "$DEST" ]; then
    log "目标存在：$DEST（$(find "$DEST/web" -type f 2>/dev/null | wc -l) 个 web 文件）"
  else
    warn "目标不存在（dry-run 不创建）"
  fi
fi

# ---- 同步计划（dry-run 打印，真跑执行） --------------------------------------
SYNC_PAIRS=()
SYNC_PAIRS+=("$SRC/web|$DEST/web")
# assets/* 在发行版里是被拍平到安装根的：官方 tools/setup/build_and_install.py 第 1 步
# `for item in assets_dir.iterdir(): install_dir / item.name`。所以覆盖层铺到
# $DEST/resource_cloud_web（与 interface.json 的 "./resource_cloud_web" 对齐），不是 assets/ 下。
if [ -d "$SRC/assets/resource_cloud_web" ]; then
  SYNC_PAIRS+=("$SRC/assets/resource_cloud_web|$DEST/resource_cloud_web")
elif [ -d "$SRC/web/resource_web" ]; then
  warn "仓库还没迁到 assets/resource_cloud_web：覆盖层随 web/ 一起同步（旧布局，可用）"
else
  warn "找不到网页端覆盖层（assets/resource_cloud_web 与 web/resource_web 都不在）"
fi

EXCLUDES=(
  --exclude=probe_out/
  --exclude=__pycache__/
  --exclude=.ruff_cache/
  --exclude=.pytest_cache/
  --exclude='*.pyc'
  --exclude='*.log'
  --exclude='.bak-*'
  --exclude='*.bak-*'
  --exclude='/linux/tools/'
)

print_sync_plan() {
  local pair
  log "同步计划（rsync -a --delete，排除 probe_out/__pycache__/*.log/*.bak-*/linux/tools）："
  for pair in "${SYNC_PAIRS[@]}"; do
    log "  ${pair%%|*} -> ${pair##*|}"
  done
}

do_sync() {
  local pair src dst
  for pair in "${SYNC_PAIRS[@]}"; do
    src="${pair%%|*}"
    dst="${pair##*|}"
    if command -v rsync >/dev/null 2>&1; then
      # 先给一眼「会删什么」，再真删；删除范围仅限 web/ 与覆盖层目录，且已整份备份
      rsync -a --delete --dry-run --itemize-changes "${EXCLUDES[@]}" "$src/" "$dst/" 2>/dev/null \
        | awk '$1 ~ /^\*/ {print}' | head -20 | sed 's/^/[deploy]   /'
      if ! rsync -a --delete "${EXCLUDES[@]}" "$src/" "$dst/"; then
        die "rsync 失败: $src -> $dst" 5
      fi
    else
      mkdir -p "$dst"
      if ! tar -C "$src" -cf - . | tar -C "$dst" -xf -; then
        die "tar 同步失败: $src -> $dst" 5
      fi
    fi
    log "已同步 ${src##*/} -> $dst"
  done
}

# ---- 备份与回滚 --------------------------------------------------------------
# 回滚脚本里的 $DEST/$BK 要在回滚时展开，所以生成时故意用单引号（SC2016 是误报）。
# shellcheck disable=SC2016
write_rollback() {
  local bk="$1" rb="$1/rollback.sh"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%s\n' "# 回滚到本次部署前（由 deploy.sh 生成，$(date -Is)）"
    printf '%s\n' 'set -euo pipefail'
    printf 'DEST=%q\n' "$DEST"
    printf 'BK=%q\n' "$bk"
    printf '%s\n' 'if pgrep -f "run_daily_linux[.]py" >/dev/null 2>&1; then'
    printf '%s\n' '  echo "有任务在跑，先跑 homesrv/stop_homesrv.sh"; exit 1'
    printf '%s\n' 'fi'
    printf '%s\n' 'rm -rf "$DEST/web" && cp -a "$BK/web.d" "$DEST/web"'
    printf '%s\n' 'if [ -d "$BK/tasks.d" ]; then rm -rf "$DEST/tasks" && cp -a "$BK/tasks.d" "$DEST/tasks"; fi'
    printf '%s\n' 'if [ -d "$BK/assets.d" ]; then rm -rf "$DEST/assets" && cp -a "$BK/assets.d" "$DEST/assets"; fi'
    printf '%s\n' 'if [ -f "$BK/interface.json" ]; then cp -a "$BK/interface.json" "$DEST/interface.json"; fi'
    printf '%s\n' 'if [ -d "$BK/patched.d" ]; then cp -a "$BK/patched.d/." "$DEST/"; fi'
    printf '%s\n' 'echo "[rollback] 已回滚到部署前：$(date -Is)"'
  } >"$rb"
  chmod +x "$rb"
}

do_backup() {
  local ts="$1" bk
  bk="$DEST/backups/deploy-$ts"
  mkdir -p "$bk" || die "建备份目录失败: $bk" 4
  if [ -d "$DEST/web" ]; then
    cp -a "$DEST/web" "$bk/web.d" || die "备份 web/ 失败" 4
  else
    warn "没有 $DEST/web 可备份（首次部署）"
  fi
  if [ -d "$DEST/tasks" ]; then
    cp -a "$DEST/tasks" "$bk/tasks.d"
  fi
  if [ -d "$DEST/assets" ]; then
    cp -a "$DEST/assets" "$bk/assets.d"
  fi
  if [ -f "$DEST/interface.json" ]; then
    cp -a "$DEST/interface.json" "$bk/interface.json"
  fi
  # 覆盖层会改 resource/ 里的个别文件（overlay_ops.json 的 text_patches）；只备份这几个，
  # 不整份拷 resource/（几百 MB，每天备份不划算）。
  if [ -f "$SRC/web/linux/homesrv/overlay_ops.json" ]; then
    python3 - "$DEST" "$bk" "$SRC/web/linux/homesrv/overlay_ops.json" <<'PY' || warn "备份待修补文件失败（回滚后 resource 可能仍是新内容）"
import json
import shutil
import sys
from pathlib import Path

dest, bk, ops = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
data = json.loads(ops.read_text(encoding="utf-8-sig"))
for patch in data.get("text_patches") or []:
    rel = patch.get("file") or ""
    src = dest / rel
    if not rel or not src.is_file():
        continue
    dst = bk / "patched.d" / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print("[deploy] 已备份待修补文件: %s" % rel)
PY
  fi
  {
    printf '部署备份 %s\n' "$ts"
    printf '源: %s\n' "$SRC"
    printf '目标: %s\n' "$DEST"
    printf 'lib.sh md5: %s\n' "$(md5sum "$SRC/web/linux/homesrv/lib.sh" | cut -d' ' -f1)"
    printf 'web 文件数: %s\n' "$(find "$DEST/web" -type f 2>/dev/null | wc -l)"
  } >"$bk/MANIFEST.txt"
  write_rollback "$bk"
  log "已备份到 $bk（回滚：bash $bk/rollback.sh）"
}

# 旧部署备份只留最近 KEEP 份，避免每次部署都堆一份 3MB 的 web/。
prune_deploy_backups() {
  local d line rows=()
  [ -d "$DEST/backups" ] || return 0
  for d in "$DEST"/backups/deploy-*/; do
    [ -d "$d" ] || continue
    rows+=("$(stat -c %Y "$d" 2>/dev/null || echo 0) $d")
  done
  if [ "${#rows[@]}" -le "$KEEP" ]; then
    return 0
  fi
  printf '%s\n' "${rows[@]}" | sort -rn | tail -n +$((KEEP + 1)) | while IFS= read -r line; do
    d="${line#* }"
    [ -n "$d" ] || continue
    rm -rf "$d"
    log "清理旧部署备份 $(basename "$d")"
  done
  return 0
}

# ---- 部署后检查 --------------------------------------------------------------
post_checks() {
  local f tmp
  log "部署后检查：shell 语法 / python 编译 / 包导入 / 覆盖层"
  [ -f "$DEST/web/linux/homesrv/lib.sh" ] || die "同步后缺 $DEST/web/linux/homesrv/lib.sh（同步路径不对？）" 6
  for f in "$DEST"/web/linux/homesrv/*.sh; do
    [ -e "$f" ] || continue
    bash -n "$f" || die "部署后 bash -n 失败: $f" 6
  done
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/maaend-deploy-post-XXXXXX")
  for f in "$DEST"/web/linux/homesrv/*.py; do
    [ -e "$f" ] || continue
    if ! PYTHONPYCACHEPREFIX="$tmp" python3 -m py_compile "$f"; then
      rm -rf "$tmp"
      die "部署后 python 编译失败: $f" 6
    fi
  done
  rm -rf "$tmp"

  # core/config 不 import maa：没有框架的机器也必须能导入（PLAN §7 sa-2 验收同款）。
  if ! python3 -c "import sys; sys.path.insert(0, '$DEST/web/linux'); import maaend_web.config as c; print('[deploy] 可导入 maaend_web.config ->', c.__file__)"; then
    die "部署后无法导入 maaend_web.config" 6
  fi

  python3 "$DEST/web/linux/homesrv/overlay_apply.py" --root "$DEST" --src "$DEST" --check \
    || die "覆盖层没叠回：升级后 tasks/interface 会与发行版对不上" 6
  log "部署后检查通过"
}

# ---- 行为自检（run_daily --dry-run） -----------------------------------------
selfcheck_daily() {
  local conf="$DEST/daily.conf" instance tasks out rc
  instance=""
  tasks=""
  if [ -f "$conf" ]; then
    instance=$(grep -E '^INSTANCE=' "$conf" | tail -1 | cut -d= -f2- | sed 's/#.*//' | tr -d '"'"'"' ' || true)
    tasks=$(grep -E '^TASKS=' "$conf" | tail -1 | cut -d= -f2- | sed 's/#.*//' | tr -d '"' || true)
  fi
  instance="${instance:-${MAAEND_INSTANCE:-}}"
  if [ -z "$instance" ]; then
    warn "没有预设实例（$conf 缺 INSTANCE），跳过 run_daily --dry-run 自检"
    return 0
  fi
  if [ ! -f "$DEST/config/mxu-MaaEnd.json" ]; then
    warn "没有 $DEST/config/mxu-MaaEnd.json（MXU 预设未配置），跳过行为自检"
    return 0
  fi
  out=$(mktemp "${TMPDIR:-/tmp}/maaend-deploy-dryrun-XXXXXX")
  local args=(--instance "$instance" --dry-run)
  if [ -n "$tasks" ]; then
    args+=(--tasks "$tasks")
  fi
  (cd "$DEST" && MAAEND_DIST="$DEST" MAAEND_ROOT="$DEST" timeout 180 \
      python3 web/linux/run_daily_linux.py "${args[@]}" >"$out" 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    grep -E "待跑|资源加载|覆盖 " "$out" | head -6 | sed 's/^/[deploy]   /'
    rm -f "$out"
    log "行为自检通过（run_daily --dry-run）"
    return 0
  fi
  tail -20 "$out" | sed 's/^/[deploy]   /'
  rm -f "$out"
  die "run_daily --dry-run 失败（rc=$rc）" 7
}

# ---- 主流程 ------------------------------------------------------------------
TS=$(date +%Y%m%d-%H%M%S)
BK_TARGET="$DEST/backups/deploy-$TS"

if [ "$DRY" = "1" ]; then
  print_sync_plan
  log "叠回计划（只读）：stage $SRC/assets/tasks 的 include 列表 -> $DEST/web/tasks，再 apply 到 tasks/ + interface import + resource 修补"
  if [ -f "$SRC/web/linux/homesrv/overlay_apply.py" ] && [ -d "$DEST" ]; then
    python3 "$SRC/web/linux/homesrv/overlay_apply.py" --root "$DEST" --dry-run --stage-from "$SRC" \
      --ops "$SRC/web/linux/homesrv/overlay_ops.json" \
      || warn "叠回预演有失败项（真部署会在这一步中止）"
  fi
  log "行为自检将执行：cd $DEST && python3 web/linux/run_daily_linux.py --instance <daily.conf 里的 INSTANCE> --dry-run"
  log "备份将写到：$BK_TARGET（回滚：bash $BK_TARGET/rollback.sh）"
  log "dry-run 结束：未备份、未同步、未写任何文件"
  exit 0
fi

if [ "$YES" != "1" ]; then
  if [ -t 0 ]; then
    printf '[deploy] 即将部署 %s -> %s，回车继续（Ctrl-C 取消）：' "$SRC" "$DEST"
    read -r _ || true
  else
    die "非交互环境请加 --yes" 2
  fi
fi

do_backup "$TS"
do_sync
python3 "$DEST/web/linux/homesrv/overlay_apply.py" --root "$DEST" --stage-from "$SRC" || die "叠回覆盖层失败" 6
post_checks
if [ "$SELFCHECK" = "1" ]; then
  selfcheck_daily
fi
prune_deploy_backups

log "部署完成：$TS"
log "  源:   $SRC"
log "  目标: $DEST"
log "  备份: $BK_TARGET"
log "  回滚: bash $BK_TARGET/rollback.sh"
log "  生效: cron 03:00 的 nightly_run_homesrv.sh；手动跑 $DEST/web/linux/homesrv/nightly_run_homesrv.sh"
exit 0
