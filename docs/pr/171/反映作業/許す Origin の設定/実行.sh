#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。常駐アプリの settings.toml の [api] に、ゲートウェイの公開のサブドメインを許す Origin として書き、常駐アプリを起動し直す
set -uo pipefail

SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml
BACKUP=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml.bak-pr171
ORIGIN=https://voice-paste.shuhdev.com
NEW=$(mktemp)
trap 'rm -f "$NEW"' EXIT

# 前提確認
if [ ! -f "$SETTINGS" ] || [ ! -f voice-paste.bat ] \
  || ! python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$SETTINGS" 2> /dev/null; then
  echo "前提確認: failed"
  exit 1
fi
echo "前提確認: ok"

# 計画（--dry-run もここを通る）
# 既に許しているか、キーが空のリストか、別の値で書かれているか、[api] があるかを読む
STATE=$(python3 - "$SETTINGS" "$ORIGIN" <<'PY'
import sys, tomllib
api = tomllib.load(open(sys.argv[1], "rb")).get("api")
if api is None:
    print("no_api")
elif "allowed_web_origins" not in api:
    print("absent")
elif sys.argv[2] in api["allowed_web_origins"]:
    print("present")
elif api["allowed_web_origins"] == []:
    print("empty")
else:
    print("other")
PY
)
case "$STATE" in
  present)
    echo "許す Origin の書き込み: skipped"
    exit 0
    ;;
  absent | empty) ;;
  *)
    # [api] が無い、または別の Origin が書いてある: 手で決める必要があるため依頼元へ返す
    echo "許す Origin の書き込み: failed（$STATE）"
    exit 1
    ;;
esac

LINE="allowed_web_origins = [\"$ORIGIN\"]"
EMPTY_LINE='^[[:space:]]*allowed_web_origins[[:space:]]*=[[:space:]]*[[][[:space:]]*[]][[:space:]]*$'
if [ "$STATE" = empty ]; then
  # [api] の中の allowed_web_origins = [] の行をちょうど 1 行見つけて置き換える
  HITS=$(awk -v pat="$EMPTY_LINE" '/^\[/ { in_api = ($0 == "[api]") } in_api && $0 ~ pat { n++ } END { print n + 0 }' "$SETTINGS")
  if [ "$HITS" != 1 ]; then
    echo "許す Origin の書き込み: failed（empty）"
    exit 1
  fi
  awk -v pat="$EMPTY_LINE" -v line="$LINE" '/^\[/ { in_api = ($0 == "[api]") } in_api && $0 ~ pat { print line; next } { print }' "$SETTINGS" > "$NEW"
else
  # [api] の見出しの次の行に書き足す
  awk -v line="$LINE" '{ print } $0 == "[api]" { print line }' "$SETTINGS" > "$NEW"
fi
diff -u --label "$SETTINGS" --label "$SETTINGS" "$SETTINGS" "$NEW"
if [ "${1:-}" = "--dry-run" ]; then
  echo "許す Origin の書き込み: changed"
  echo "常駐アプリの起動し直し: changed"
  exit 0
fi

# 適用（検証 → 退避 → 置き換え）
if ! python3 -c 'import sys, tomllib; assert sys.argv[2] in tomllib.load(open(sys.argv[1], "rb"))["api"]["allowed_web_origins"]' "$NEW" "$ORIGIN" 2> /dev/null; then
  echo "検証: failed"
  exit 1
fi
echo "検証: ok"
cp -p "$SETTINGS" "$BACKUP"
cat "$NEW" > "$SETTINGS"
echo "許す Origin の書き込み: changed"

# 起動のバッチファイルは、動いている前の常駐アプリに終了を頼んでから新しく立てる
if ! cmd.exe /c voice-paste.bat; then
  echo "常駐アプリの起動し直し: failed"
  exit 1
fi
echo "常駐アプリの起動し直し: changed"
