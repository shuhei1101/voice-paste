#!/usr/bin/env bash
# ゲートウェイが動いている WSL で叩く。ゲートウェイの設定ファイル・常駐サービス・登録の一覧・常駐アプリの設定へ読み取りだけでつながるかを確かめる
set -uo pipefail

GW_SETTINGS=$HOME/.config/shuhdev-gateway/settings.toml
VP_SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml

if python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$GW_SETTINGS" 2> /dev/null; then
  echo "ゲートウェイの設定ファイル: ok"
else
  echo "ゲートウェイの設定ファイル: failed"
  exit 1
fi

if systemctl --user is-active --quiet shuhdev-gateway; then
  echo "ゲートウェイの常駐サービス: ok"
else
  echo "ゲートウェイの常駐サービス: failed"
  exit 1
fi

if gw ls > /dev/null 2>&1; then
  echo "登録の一覧: ok"
else
  echo "登録の一覧: failed"
  exit 1
fi

if python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$VP_SETTINGS" 2> /dev/null; then
  echo "常駐アプリの設定ファイル: ok"
else
  echo "常駐アプリの設定ファイル: failed"
  exit 1
fi
