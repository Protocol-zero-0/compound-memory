#!/usr/bin/env bash
# compound-memory 一键安装:认出本机装了哪些 harness → 装开局注入 → 装每晚 cron
#                            → 立刻跑一次提炼 → 打印快照
#
#   bash install.sh                     # 交互问一下你叫什么,其余全默认
#   bash install.sh --name 张三 --yes   # 全自动
#   bash install.sh --no-cron --no-inject --no-first-run   # 只铺文件,什么都不接
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CM_HOME="${CM_HOME:-$HOME/.compound-memory}"
NAME=""; MODEL=""; SINK=""; LANG_=""; ASSUME_YES=0
DO_CRON=1; DO_INJECT=1; DO_FIRST=1; FIRST_LIMIT=5

while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --sink) SINK="$2"; shift 2;;
    --language) LANG_="$2"; shift 2;;
    --limit) FIRST_LIMIT="$2"; shift 2;;
    --no-cron) DO_CRON=0; shift;;
    --no-inject) DO_INJECT=0; shift;;
    --no-first-run) DO_FIRST=0; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) sed -n '2,8p' "$0"; exit 0;;
    *) echo "不认识的参数:$1" >&2; exit 2;;
  esac
done

say() { printf '%s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ---- 1. python ----
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  command -v "$c" >/dev/null 2>&1 || continue
  "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null || continue
  PY="$c"; break
done
[ -n "$PY" ] || { echo "需要 python3.9 以上,没找到。" >&2; exit 1; }

step "1/5  环境"
say "  仓库      $REPO"
say "  数据目录  $CM_HOME"
say "  python    $($PY -V 2>&1) ($(command -v $PY))"

# ---- 2. 配置 ----
step "2/5  配置"
mkdir -p "$CM_HOME"
CFG="$CM_HOME/config.yaml"
if [ -f "$CFG" ]; then
  say "  已有配置,不覆盖:$CFG"
else
  cp "$REPO/config.example.yaml" "$CFG"
  if [ -z "$NAME" ] && [ "$ASSUME_YES" = 0 ] && [ -t 0 ]; then
    printf '  记忆是"关于你"的。你希望 AI 怎么称呼你?[%s] ' "${USER:-you}"
    read -r NAME || true
  fi
  NAME="${NAME:-${USER:-you}}"
  "$PY" - "$CFG" "$NAME" "$MODEL" "$SINK" "$LANG_" <<'PYEOF'
import re, sys
p, name, model, sink, lang = sys.argv[1:6]
s = open(p, encoding='utf-8').read()
s = re.sub(r'(?m)^user_name:.*$', f'user_name: {name}', s, count=1)
if model: s = re.sub(r'(?m)^model:.*$', f'model: {model}', s, count=1)
if sink:  s = re.sub(r'(?m)^sink:.*$',  f'sink: {sink}', s, count=1)
if lang:  s = re.sub(r'(?m)^language:.*$', f'language: {lang}', s, count=1)
open(p, 'w', encoding='utf-8').write(s)
PYEOF
  say "  已生成 $CFG(称呼:$NAME)"
fi

# ---- 3. 接上 ----
step "3/5  接到本机的 harness 上"
ARGS=""
[ "$DO_INJECT" = 1 ] || ARGS="$ARGS --no-inject"
[ "$DO_CRON" = 1 ] || ARGS="$ARGS --no-cron"
CM_HOME="$CM_HOME" "$REPO/bin/cm" install $ARGS

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) say ""; say "  提示:~/.local/bin 不在 PATH 里。加一行到 ~/.bashrc:"
     say '        export PATH="$HOME/.local/bin:$PATH"';;
esac

# ---- 4. 先跑一次 ----
step "4/5  第一次提炼(只看最近几天,先证明它是通的)"
if [ "$DO_FIRST" = 0 ]; then
  say "  跳过(--no-first-run)。想跑:cm distill --days 7 --limit 5"
else
  if CM_HOME="$CM_HOME" "$REPO/bin/cm" distill --days 7 --limit "$FIRST_LIMIT"; then
    :
  else
    say ""
    say "  第一次提炼没跑成。最常见的两个原因:"
    say "    · 模型调不通 —— 默认用本机已登录的 \`claude\`;没有的话改 config.yaml 的 llm.backend 为 openai"
    say "    · 最近 7 天没有够长的对话 —— 试 cm distill --days 60 --limit 5"
    say "  诊断:cm doctor"
  fi
fi

# ---- 5. 结果 ----
step "5/5  装好了"
say "  cm doctor            看现状"
say "  cm snapshot          打印当前快照(开局注入的就是它)"
say '  cm recall "话题"     按话题检索记忆'
say "  cm uninstall         原样摘掉(改动都有备份,在 $CM_HOME/backups/)"
say ""
CM_HOME="$CM_HOME" "$REPO/bin/cm" snapshot || true
