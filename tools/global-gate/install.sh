#!/usr/bin/env bash
# 把推送隐私闸装成**本机全局**:所有仓库推到 GitHub 之前都先过闸。
#
#   bash tools/global-gate/install.sh              # 装(或重装,幂等)
#   bash tools/global-gate/install.sh --uninstall  # 原样摘掉
#
# 做了什么(全部可撤销,原值都记在 $DEST/state/):
#   1. 把闸门脚本拷到 ~/.config/git/privacy-gate/(跟本仓库解耦,仓库挪走也不失效)
#   2. git config --global core.hooksPath 指向那里;其余钩子都转回仓库自己原来的,不会失效
#   3. 自己设了 core.hooksPath 的仓库(husky 之类)全局设置管不到,逐个"包一层"
#   4. 每晚 cron:重建原文指纹索引 + 检查有没有仓库脱离了闸门
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DEST="${PRIVACY_GATE_HOME:-$HOME/.config/git/privacy-gate}"
CM_HOME="${CM_HOME:-$HOME/.compound-memory}"
ROOTS="${PRIVACY_GATE_ROOTS:-$HOME}"
TAG='# privacy-gate'
HOOKS="applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit prepare-commit-msg
commit-msg post-commit pre-rebase post-checkout post-merge pre-auto-gc post-rewrite
sendemail-validate fsmonitor-watchman post-index-change reference-transaction push-to-checkout
p4-changelist p4-prepare-changelist p4-post-changelist p4-pre-submit"

repos_with_local_hookspath() {
  # 仓库级(--local)和工作区级(--worktree,比如 deepseek-harness)都会盖过全局,两层都要找
  find $ROOTS -maxdepth 5 -name .git \( -type d -o -type f \) -not -path '*/node_modules/*' 2>/dev/null |
  while read -r g; do
    d=$(dirname "$g")
    line=$(git -C "$d" config --show-scope --get core.hooksPath 2>/dev/null || true)
    scope=${line%%$'\t'*}; v=${line#*$'\t'}
    case "$scope" in local|worktree) printf '%s\t%s\t%s\n' "$d" "$v" "$scope" ;; esac
  done
}

uninstall() {
  if [ -f "$DEST/state/global-hookspath" ]; then
    old=$(cat "$DEST/state/global-hookspath")
    if [ -n "$old" ]; then git config --global core.hooksPath "$old"; else git config --global --unset core.hooksPath || true; fi
  fi
  if [ -f "$DEST/state/wrapped.tsv" ]; then
    while IFS=$'\t' read -r d old scope; do
      [ -d "$d" ] || continue
      scope=${scope:-local}
      git -C "$d" config --$scope core.hooksPath "$old"
      git -C "$d" config --$scope --unset privacy-gate.chain || true
      echo "  还原 $d → $old"
    done < "$DEST/state/wrapped.tsv"
  fi
  crontab -l 2>/dev/null | grep -v "$TAG" | crontab - || true
  echo "已摘掉全局隐私闸(脚本留在 $DEST,要删手动删)"
}

[ "${1:-}" = "--uninstall" ] && { uninstall; exit 0; }

mkdir -p "$DEST/hooks" "$DEST/state"
# 1. 拷脚本
cp "$REPO/tools/privacy-check.py" "$DEST/privacy-check.py"
cp "$HERE/pre-push" "$HERE/_dispatch" "$DEST/hooks/"
cp "$HERE/health.sh" "$DEST/health.sh"
chmod +x "$DEST/hooks/pre-push" "$DEST/hooks/_dispatch" "$DEST/health.sh"
for h in $HOOKS; do ln -sfn _dispatch "$DEST/hooks/$h"; done
echo "  脚本 → $DEST"

# 2. 全局 hooksPath(原值只记第一次,重装不覆盖)
cur=$(git config --global --get core.hooksPath || true)
if [ "$cur" != "$DEST/hooks" ]; then
  [ -f "$DEST/state/global-hookspath" ] || printf '%s' "$cur" > "$DEST/state/global-hookspath"
  git config --global core.hooksPath "$DEST/hooks"
fi
echo "  全局 core.hooksPath → $DEST/hooks"

# 3. 自带 hooksPath 的仓库:记下原值,改指向闸门,闸门再转回原值
touch "$DEST/state/wrapped.tsv"
n=0
while IFS=$'\t' read -r d v scope; do
  [ "$v" = "$DEST/hooks" ] && continue
  printf '%s\t%s\t%s\n' "$d" "$v" "$scope" >> "$DEST/state/wrapped.tsv"
  git -C "$d" config --$scope privacy-gate.chain "$v"
  git -C "$d" config --$scope core.hooksPath "$DEST/hooks"
  echo "  包一层 $d(原 hooksPath=$v,$scope 级)"; n=$((n+1))
done < <(repos_with_local_hookspath)
echo "  自带 hooksPath 的仓库:新包 $n 个"

# 4. 词表 / 索引 / cron
[ -f "$CM_HOME/privacy-terms.txt" ] || { mkdir -p "$CM_HOME"; printf '# 一行一个正则,默认区分大小写;要不区分就写 (?i) 开头\n# 例:\n# 张三\n# (?i)acme corp\n' > "$CM_HOME/privacy-terms.txt"; echo "  !! 词表是空的,去填:$CM_HOME/privacy-terms.txt"; }
"$REPO/bin/cm" privacy-index >/dev/null 2>&1 && echo "  原文指纹索引已建" || echo "  !! 索引没建成,只有词表那一道在工作;手动跑 cm privacy-index 看原因"
if command -v crontab >/dev/null; then
  line="15 3 * * * cd $REPO && PRIVACY_GATE_ROOTS='$ROOTS' bash $DEST/health.sh $REPO >> $CM_HOME/privacy-gate-health.log 2>&1  $TAG"
  { crontab -l 2>/dev/null | grep -v "$TAG"; echo "$line"; } | crontab -
  echo "  每晚 03:15 重建索引 + 巡检"
fi
echo "装好了。验证:在任意仓库里 git push --dry-run 应看到「隐私闸:…」"
