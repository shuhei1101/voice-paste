#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。作業ツリーの改行コードが .gitattributes の eol と食い違うファイルを、中身が index と同じことを確かめてから index から書き出し直す
set -uo pipefail

# 前提確認
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1 || ! git cat-file -e HEAD:.gitattributes 2> /dev/null; then
  echo "前提確認: failed"
  exit 1
fi
echo "前提確認: ok"

# 計画（--dry-run もここを通る）
# index が LF のファイルのうち、作業ツリーの改行コード（w/）が属性の eol と違うものを集める
TARGETS=()
DIFFERS=()
while IFS= read -r -d '' ENTRY; do
  META=${ENTRY%%$'\t'*}
  FILE=${ENTRY#*$'\t'}
  read -r INDEX_EOL WORK_EOL ATTR <<< "$META"
  [ "$INDEX_EOL" = "i/lf" ] || continue
  case "$ATTR" in
    *eol=crlf*) WANT="w/crlf" ;;
    *eol=lf*) WANT="w/lf" ;;
    *) continue ;;
  esac
  case "$WORK_EOL" in
    w/lf | w/crlf) ;;
    *) continue ;;
  esac
  [ "$WORK_EOL" = "$WANT" ] && continue
  # 改行コードを除いた中身が index と違うファイルは書き出し直さない
  if git diff --quiet -- "$FILE"; then
    TARGETS+=("$FILE")
    echo "書き出し直す: $FILE（$WORK_EOL → $WANT）"
  else
    DIFFERS+=("$FILE")
    echo "中身の差がある: $FILE"
  fi
done < <(git ls-files --eol -z)

if [ "${#DIFFERS[@]}" -gt 0 ]; then
  echo "中身の差の確認: failed"
  exit 1
fi
echo "中身の差の確認: ok"

if [ "${#TARGETS[@]}" -eq 0 ]; then
  echo "作業ツリーの書き出し直し: skipped"
  exit 0
fi
if [ "${1:-}" = "--dry-run" ]; then
  echo "作業ツリーの書き出し直し: changed"
  exit 0
fi

# 適用
# checkout-index は stat が index と合うファイルを書き直さないため、先に更新時刻を index と違う値にする（書き出しで今の時刻に戻る）
if ! touch -d @0 -- "${TARGETS[@]}" || ! git checkout-index -f -- "${TARGETS[@]}"; then
  echo "作業ツリーの書き出し直し: failed"
  exit 1
fi
echo "作業ツリーの書き出し直し: changed"

# index に残る書き出し前のサイズ・時刻を取り直す（中身は計画で index と同じと確かめている）
if ! git update-index -- "${TARGETS[@]}"; then
  echo "index の記録の取り直し: failed"
  exit 1
fi
echo "index の記録の取り直し: changed"
