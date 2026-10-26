#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。設定に許す Origin があり、その Origin の /web/ の下の要求が 403 で断られないことを読むだけで確かめる
set -uo pipefail

SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml
ORIGIN=https://voice-paste.shuhdev.com
FAILED=0

if python3 -c 'import sys, tomllib; assert sys.argv[2] in tomllib.load(open(sys.argv[1], "rb"))["api"]["allowed_web_origins"]' "$SETTINGS" "$ORIGIN" 2> /dev/null; then
  echo "設定の許す Origin: ok"
else
  echo "設定の許す Origin: failed"
  FAILED=1
fi

PORT=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("api", {}).get("port", 47823))' "$SETTINGS")
# 無いジョブの状態を引く: 守りを通れば 404、Origin が許されていなければ 403
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
CODE=$(curl -s -o "$BODY" -w '%{http_code}' -m 5 -H "Host: localhost:$PORT" -H "Origin: $ORIGIN" \
  "http://127.0.0.1:$PORT/web/transcriptions/pr171-check")
if [ "$CODE" = "404" ]; then
  echo "許す Origin の要求（$PORT）: ok（$CODE）"
else
  echo "許す Origin の要求（$PORT）: failed（$CODE）"
  cat "$BODY"
  FAILED=1
fi

exit "$FAILED"
