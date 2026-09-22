#!/usr/bin/env bash
# 原样摘掉 compound-memory 的三处开局注入、cron 和 ~/.local/bin/cm。
# 记忆默认保留;要一起删:bash uninstall.sh --purge
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$REPO/bin/cm" uninstall "$@"
