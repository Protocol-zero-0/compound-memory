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

# ---- GitHub 那一侧 ----
# 词表改了,各仓库 Action 用的加密词表要跟着更新,否则 GitHub 上一直在用旧词表查
TERMS="$CM_HOME/privacy-terms.txt"
REPOS="$DEST/state/action-repos.txt"          # 装了 privacy-gate Action 的仓库,一行一个 owner/repo
if [ -s "$REPOS" ] && [ -f "$TERMS" ] && command -v gh >/dev/null; then
  h=$(sha256sum "$TERMS" | cut -c1-16)
  if [ "$h" != "$(cat "$DEST/state/terms-synced.sha" 2>/dev/null)" ]; then
    fail=0
    while read -r r; do [ -n "$r" ] && { gh secret set PRIVACY_TERMS -R "$r" < "$TERMS" >/dev/null 2>&1 || fail=$((fail+1)); }; done < "$REPOS"
    if [ $fail -eq 0 ]; then echo "$h" > "$DEST/state/terms-synced.sha"; echo "$(ts) 词表已同步到 $(wc -l < "$REPOS") 个仓库"
    else alert "隐私闸:词表同步到 GitHub 有 $fail 个仓库失败" "明晚会重试;看 gh auth status"; fi
  fi
  # 你名下新建了自有仓库、还没装 Action:只通知,不自动装(那是对外改动)
  owner=$(git config --global --get privacy-gate.github-owner || true)
  if [ -n "$owner" ]; then
    new=$(gh repo list "$owner" --limit 300 --json nameWithOwner,isFork,isArchived --jq '.[] | select(.isFork==false and .isArchived==false) | .nameWithOwner' 2>/dev/null | sort | comm -23 - <(sort "$REPOS"))
    [ -n "$new" ] && alert "隐私闸:有新仓库还没装 GitHub 侧复查" "$(echo $new | tr ' ' ',')"
  fi
fi
exit 0
