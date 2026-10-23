#!/usr/bin/env bash
# ゲートウェイが動いている WSL で叩く。実行.sh が退避したゲートウェイの設定を書き戻し、ゲートウェイを再起動する
set -uo pipefail

GW_SETTINGS=$HOME/.config/shuhdev-gateway/settings.toml
BACKUP=$HOME/.config/shuhdev-gateway/settings.toml.bak-pr171

if [ ! -f "$BACKUP" ]; then
  echo "退避したファイル: failed"
  exit 1
fi
cp -p "$BACKUP" "$GW_SETTINGS"
echo "設定の書き戻し: changed"

if ! systemctl --user restart shuhdev-gateway || ! systemctl --user is-active --quiet shuhdev-gateway; then
  echo "ゲートウェイの再起動: failed"
  exit 1
fi
echo "ゲートウェイの再起動: changed"
