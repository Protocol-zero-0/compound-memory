#!/usr/bin/env bash
# 给一个 GitHub 仓库装上"推送后隐私复查",全自动、幂等,重复跑安全。
#
#   action-install.sh <owner/repo> [strict|publish]
#
# 顺序是讲究过的:
#   1. 先设加密词表和档位 —— 反过来的话,workflow 第一次运行时密文还没到,检查直接失败
#   2. 确保这个仓库的 Actions 是开着的
#   3. 再推 workflow 文件。走 SSH:gh 的 OAuth 令牌没有 workflow 权限,走 HTTPS 会被 GitHub 拒绝
#   4. 本机有这个仓库的副本且干净、同步:就在副本里提交再推,推完副本仍然同步;
#      副本有改动或不同步:这次跳过,下次再试 —— 从远端硬推会让那份副本落后,它下次推送会被拒
# 退出码:0 装好了 / 已经装过;10 这次先跳过(空仓库、副本不同步),下次再试;其他 = 出错
set -uo pipefail
r="${1:?用法: action-install.sh <owner/repo> [strict|publish]}"; mode="${2:-strict}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="${PRIVACY_ACTION_TEMPLATE:-$HERE/privacy-gate.yml}"
CM_HOME="${CM_HOME:-$HOME/.compound-memory}"
TERMS="$CM_HOME/privacy-terms.txt"
ROOTS="${PRIVACY_GATE_ROOTS:-$HOME}"
path=.github/workflows/privacy-gate.yml
say() { printf '%s\n' "$*"; }

[ -f "$TPL" ] || { say "找不到模板 $TPL"; exit 2; }
[ -s "$TERMS" ] || { say "词表是空的:$TERMS"; exit 2; }
info=$(gh api "repos/$r" --jq '"\(.default_branch // "")\t\(.size)\t\(.archived)\t\(.fork)"' 2>/dev/null) || { say "$r:读不到仓库信息"; exit 2; }
IFS=$'\t' read -r br size archived fork <<< "$info"
[ "$archived" = "true" ] && { say "$r:已归档,跳过"; exit 0; }
[ "$fork" = "true" ] && { say "$r:是 fork(给别人提 PR 用),不装"; exit 0; }

# 1) 密文 + 档位
gh secret set PRIVACY_TERMS -R "$r" < "$TERMS" >/dev/null 2>&1 || { say "$r:设密文失败"; exit 3; }
if [ "$mode" = "publish" ]; then gh variable set PRIVACY_MODE -R "$r" --body publish >/dev/null 2>&1
else gh variable delete PRIVACY_MODE -R "$r" >/dev/null 2>&1 || true; fi

# 2) Actions 开着
gh api -X PUT "repos/$r/actions/permissions" -F enabled=true -f allowed_actions=all >/dev/null 2>&1 || true

# 3) workflow 文件
if [ -z "$br" ] || [ "$size" = "0" ] && ! gh api "repos/$r/commits?per_page=1" >/dev/null 2>&1; then
  say "$r:还是空仓库(没有任何提交),等有了第一个提交再装"; exit 10
fi
remote=$(gh api "repos/$r/contents/$path?ref=$br" --jq '.content' 2>/dev/null | tr -d '\n' | base64 -d 2>/dev/null)
code() { grep -v '^[[:space:]]*#' | sed '/^[[:space:]]*$/d'; }     # 只比实际生效的内容,注释改了不值得一次提交
if [ -n "$remote" ] && [ "$(printf '%s\n' "$remote" | code)" = "$(code < "$TPL")" ]; then say "$r:已经装好($mode)"; exit 0; fi

ssh_url="git@github.com:$r.git"; name="${r#*/}"
local_clone=""
while read -r g; do d=$(dirname "$g")
  u=$(git -C "$d" remote get-url origin 2>/dev/null) || continue
  case "$u" in *"/$name.git"|*"/$name"|*":$r.git"|*":$r") ;; *) continue ;; esac
  case "$u" in *"${r%%/*}/"*) ;; *) continue ;; esac
  git -C "$d" fetch -q origin 2>/dev/null
  if [ "$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$br" ] && [ -z "$(git -C "$d" status --porcelain)" ] \
     && [ "$(git -C "$d" rev-list --left-right --count "origin/$br...HEAD" 2>/dev/null | tr '\t' '/')" = "0/0" ]; then
    local_clone="$d"; break
  fi
  say "$r:本机副本 $d 有改动或不同步,这次先不装(硬推会让它落后),下次再试"; exit 10
done < <(find $ROOTS -maxdepth 4 -name .git -type d -not -path '*/node_modules/*' 2>/dev/null)

if [ -n "$local_clone" ]; then w="$local_clone"; tmp=""
else tmp=$(mktemp -d "${TMPDIR:-$HOME/scratch}/privacy-action.XXXXXX"); w="$tmp/repo"
  git clone -q --depth 1 -b "$br" "$ssh_url" "$w" 2>/dev/null || { rm -rf "$tmp"; say "$r:拉不下来"; exit 4; }
fi
mkdir -p "$w/$(dirname "$path")"; cp "$TPL" "$w/$path"
git -C "$w" add "$path"
git -C "$w" commit -q -m $'ci: 推送后隐私复查(privacy-gate)\n\n每次推送后用加密的敏感词表复查新增内容,命中则此检查失败并发邮件通知。\n只报位置和规则序号,不回显命中原文。' -- "$path" 2>/dev/null
if git -C "$w" push -q "$ssh_url" "HEAD:$br" 2>/dev/null; then
  [ -n "$local_clone" ] && git -C "$w" fetch -q origin 2>/dev/null
  [ -n "$tmp" ] && rm -rf "$tmp"
  say "$r:已装好($mode,${local_clone:+在本机副本 $local_clone 里提交}${tmp:+临时副本})"; exit 0
fi
[ -n "$local_clone" ] && { git -C "$w" reset -q --soft HEAD~1; git -C "$w" reset -q HEAD "$path"; rm -f "$w/$path"; }
[ -n "$tmp" ] && rm -rf "$tmp"
say "$r:推送失败(分支保护?)"; exit 5
