#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。実行.sh が退避した settings.toml を書き戻し、常駐アプリを起動し直す
set -uo pipefail

SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml
BACKUP=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml.bak-pr171

if [ ! -f "$BACKUP" ]; then
  echo "退避したファイル: failed"
  exit 1
fi
cat "$BACKUP" > "$SETTINGS"
echo "設定の書き戻し: changed"

if ! cmd.exe /c voice-paste.bat; then
  echo "常駐アプリの起動し直し: failed"
  exit 1
fi
echo "常駐アプリの起動し直し: changed"
