#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。作業ツリーに変更が無く、作業ツリーが CRLF のファイルが .bat だけかを読むだけで確かめる
set -uo pipefail

FAILED=0

CHANGES=$(git status --short | grep -v '^?? \.claude/$')
if [ -z "$CHANGES" ]; then
  echo "作業ツリーの変更: ok"
else
  echo "作業ツリーの変更: failed"
  echo "$CHANGES"
  FAILED=1
fi

NOT_BAT=0
while IFS= read -r -d '' ENTRY; do
  META=${ENTRY%%$'\t'*}
  FILE=${ENTRY#*$'\t'}
  read -r _ WORK_EOL _ <<< "$META"
  [ "$WORK_EOL" = "w/crlf" ] || continue
  echo "作業ツリーが CRLF: $FILE"
  case "$FILE" in
    *.bat) ;;
    *) NOT_BAT=1 ;;
  esac
done < <(git ls-files --eol -z)

if [ "$NOT_BAT" -eq 0 ]; then
  echo "CRLF のファイルが .bat だけ: ok"
else
  echo "CRLF のファイルが .bat だけ: failed"
  FAILED=1
fi

exit "$FAILED"
