#!/bin/sh
set -eu

PR_URL=https://github.com/shuhei1101/voice-paste/pull/297
URL=$(gh api repos/shuhei1101/mdmark/issues/478/comments --paginate --jq ".[] | select(.body | contains(\"${PR_URL}\")) | .html_url" | head -n 1)
if [ -n "$URL" ]; then
  echo "shuhei1101/mdmark#478 の完了の連絡: ok ($URL)"
else
  echo "shuhei1101/mdmark#478 の完了の連絡: failed（${PR_URL} を含むコメントがありません）"
  exit 1
fi
