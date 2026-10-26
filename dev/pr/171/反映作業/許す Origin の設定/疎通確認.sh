#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。常駐アプリの設定ファイル・起動のバッチファイル・稼働中の API へ読み取りだけでつながるかを確かめる
set -uo pipefail

SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml

if python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$SETTINGS" 2> /dev/null; then
  echo "常駐アプリの設定ファイル: ok"
else
  echo "常駐アプリの設定ファイル: failed"
  exit 1
fi

if [ -f voice-paste.bat ] && cmd.exe /c ver > /dev/null 2>&1; then
  echo "起動のバッチファイル: ok"
else
  echo "起動のバッチファイル: failed"
  exit 1
fi

PORT=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("api", {}).get("port", 47823))' "$SETTINGS")
# トークンを付けない要求は 401 で断られる（API が待ち受けている）
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -H "Host: localhost:$PORT" "http://127.0.0.1:$PORT/sessions")
if [ "$CODE" = "401" ]; then
  echo "常駐アプリの API（$PORT）: ok"
else
  echo "常駐アプリの API（$PORT）: failed（$CODE）"
  exit 1
fi
