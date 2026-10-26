#!/usr/bin/env bash
# ゲートウェイが動いている WSL で叩く。voice-paste の固定の登録が一覧に出て、ゲートウェイを通した /web/ が画面を返すことを読むだけで確かめる
set -uo pipefail

VP_SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml
PORT=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("api", {}).get("port", 47823))' "$VP_SETTINGS")
FAILED=0

ROW=$(gw ls | awk '$1 == "voice-paste"')
echo "$ROW"
if echo "$ROW" | awk -v port="$PORT" '$2 == "fixed" && $3 == port { found = 1 } END { exit !found }'; then
  echo "固定の登録（$PORT 向き）: ok"
else
  echo "固定の登録（$PORT 向き）: failed"
  FAILED=1
fi

# ゲートウェイの待ち受け（127.0.0.1:8700）へ公開の Host で /web/ を引く（Cloudflare Access の手前を通る）
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Host: voice-paste.shuhdev.com" http://127.0.0.1:8700/web/)
if [ "$CODE" = "200" ]; then
  echo "ゲートウェイを通した画面: ok（$CODE）"
else
  echo "ゲートウェイを通した画面: failed（$CODE）"
  FAILED=1
fi

exit "$FAILED"
