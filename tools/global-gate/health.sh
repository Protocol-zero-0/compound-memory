#!/usr/bin/env bash
# 每晚巡检:重建原文指纹索引;把新冒出来的"自带 hooksPath"仓库重新包进闸门;
# 发现全局设置被人改掉就恢复并告警。只在有变化时说话。
set -uo pipefail
REPO="${1:?用法: health.sh <compound-memory 仓库路径>}"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CM_HOME="${CM_HOME:-$HOME/.compound-memory}"
ROOTS="${PRIVACY_GATE_ROOTS:-$HOME}"
NOTIFY="$CM_HOME/privacy-gate-notify"
ts() { date -u +%FT%TZ; }
alert() { echo "$(ts) $1: $2"; [ -x "$NOTIFY" ] && "$NOTIFY" "$1" "$2" >/dev/null 2>&1 || true; }

"$REPO/bin/cm" privacy-index >/dev/null 2>&1 || alert "隐私闸:索引重建失败" "手动跑 cm privacy-index 看原因;期间只有词表在工作"

cur=$(git config --global --get core.hooksPath || true)
if [ "$cur" != "$DEST/hooks" ]; then
  git config --global core.hooksPath "$DEST/hooks"
  alert "隐私闸:全局 hooksPath 被改掉了,已恢复" "原来是「$cur」"
fi

# 放行开关被改过就报警:mode / allow / enforce 都只该由仓库主人改
snap="$DEST/state/switches.tsv"; new="$snap.new"
find $ROOTS -maxdepth 5 -name .git \( -type d -o -type f \) -not -path '*/node_modules/*' 2>/dev/null |
while read -r g; do d=$(dirname "$g")
  v=$(git -C "$d" config --local --get-regexp '^privacy-gate\.(mode|allow|enforce)$' 2>/dev/null | sort | tr '\n' ';')
  [ -n "$v" ] && printf '%s\t%s\n' "$d" "$v"
done | sort > "$new"
if [ -f "$snap" ] && ! cmp -s "$snap" "$new"; then
  alert "隐私闸:有仓库的放行开关变了" "$(diff "$snap" "$new" | grep '^[<>]' | head -5 | tr '\n' ' ')"
fi
mv "$new" "$snap"

find $ROOTS -maxdepth 5 -name .git \( -type d -o -type f \) -not -path '*/node_modules/*' 2>/dev/null |
while read -r g; do
  d=$(dirname "$g")
  line=$(git -C "$d" config --show-scope --get core.hooksPath 2>/dev/null || true)
  scope=${line%%$'\t'*}; v=${line#*$'\t'}
  case "$scope" in local|worktree) ;; *) continue ;; esac
  [ "$v" = "$DEST/hooks" ] && continue
  printf '%s\t%s\t%s\n' "$d" "$v" "$scope" >> "$DEST/state/wrapped.tsv"
  git -C "$d" config --$scope privacy-gate.chain "$v"
  git -C "$d" config --$scope core.hooksPath "$DEST/hooks"
  alert "隐私闸:新包进一个仓库" "$d(它自己设了 hooksPath=$v,多半是 npm install 时 husky 设的)"
done
