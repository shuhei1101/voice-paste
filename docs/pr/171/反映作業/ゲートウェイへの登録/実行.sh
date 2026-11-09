#!/usr/bin/env bash
# ゲートウェイが動いている WSL で叩く。voice-paste のサブドメインを常駐アプリの API のポートへ振り分ける固定の登録を書き、ゲートウェイを再起動する
set -uo pipefail

GW_SETTINGS=$HOME/.config/shuhdev-gateway/settings.toml
BACKUP=$HOME/.config/shuhdev-gateway/settings.toml.bak-pr171
VP_SETTINGS=/mnt/c/Users/shuhe/AppData/Roaming/voice-paste/settings.toml
NEW=$(mktemp)
trap 'rm -f "$NEW"' EXIT

# 前提確認
if ! python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$GW_SETTINGS" 2> /dev/null \
  || ! python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$VP_SETTINGS" 2> /dev/null \
  || ! systemctl --user is-active --quiet shuhdev-gateway; then
  echo "前提確認: failed"
  exit 1
fi
# 振り分け先は常駐アプリの設定の api.port（無ければ既定の 47823）
PORT=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("api", {}).get("port", 47823))' "$VP_SETTINGS")
echo "前提確認: ok（振り分け先のポート $PORT）"

# 計画（--dry-run もここを通る）
STATE=$(python3 - "$GW_SETTINGS" "$PORT" <<'PY'
import sys, tomllib
entries = [e for e in tomllib.load(open(sys.argv[1], "rb")).get("fixed_registrations", []) if e.get("name") == "voice-paste"]
if not entries:
    print("absent")
elif (
    entries[0].get("port") == int(sys.argv[2])
    and entries[0].get("path") == "/web/"
    and entries[0].get("rewrite_origin", False) is False
):
    print("present")
else:
    print("other")
PY
)
case "$STATE" in
  present)
    echo "固定の登録の書き込み: skipped"
    exit 0
    ;;
  absent) ;;
  *)
    # 別の値の voice-paste の登録がある: 手で決める必要があるため依頼元へ返す
    echo "固定の登録の書き込み: failed（$STATE）"
    exit 1
    ;;
esac

{
  cat "$GW_SETTINGS"
  printf '\n[[fixed_registrations]]\nname = "voice-paste"\nport = %s\ntitle = "voice-paste の外の端末の画面"\npath = "/web/"\nrewrite_origin = false\n' "$PORT"
} > "$NEW"
diff -u --label "$GW_SETTINGS" --label "$GW_SETTINGS" "$GW_SETTINGS" "$NEW"
if [ "${1:-}" = "--dry-run" ]; then
  echo "固定の登録の書き込み: changed"
  echo "ゲートウェイの再起動: changed"
  exit 0
fi

# 適用（検証 → 退避 → 置き換え）
if ! python3 - "$NEW" "$PORT" <<'PY' 2> /dev/null
import sys, tomllib
entries = [e for e in tomllib.load(open(sys.argv[1], "rb"))["fixed_registrations"] if e.get("name") == "voice-paste"]
assert len(entries) == 1 and entries[0]["port"] == int(sys.argv[2]) and entries[0]["path"] == "/web/"
PY
then
  echo "検証: failed"
  exit 1
fi
echo "検証: ok"
cp -p "$GW_SETTINGS" "$BACKUP"
mv "$NEW" "$GW_SETTINGS"
echo "固定の登録の書き込み: changed"

if ! systemctl --user restart shuhdev-gateway || ! systemctl --user is-active --quiet shuhdev-gateway; then
  echo "ゲートウェイの再起動: failed"
  exit 1
fi
echo "ゲートウェイの再起動: changed"
