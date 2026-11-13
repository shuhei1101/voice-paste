#!/bin/sh
set -eu

PR_URL=https://github.com/shuhei1101/voice-paste/pull/297
BODY="voice-paste の文書のマーカーを JSON の記載へ移し終えました（${PR_URL}）。develop で mdmark check は legacy_mark を出しません。"

# 前提確認
if [ $# -gt 1 ] || { [ $# -eq 1 ] && [ "$1" != "--dry-run" ]; }; then
  echo "前提確認: failed"
  echo "引数は無しか --dry-run だけを受け付けます: $*"
  exit 1
fi
STATE=$(gh pr view 297 -R shuhei1101/voice-paste --json state --jq .state)
if [ "$STATE" != "MERGED" ]; then
  echo "前提確認: failed"
  echo "gh pr view 297 -R shuhei1101/voice-paste --json state"
  echo "shuhei1101/voice-paste#297 の状態が MERGED ではありません: $STATE"
  exit 1
fi
echo "前提確認: ok"

# 計画（--dry-run もここを通る）
POSTED=$(gh api repos/shuhei1101/mdmark/issues/478/comments --paginate --jq ".[] | select(.body | contains(\"${PR_URL}\")) | .id")
if [ -n "$POSTED" ]; then
  echo "shuhei1101/mdmark#478 へのコメント: skipped"
  exit 0
fi
echo "コメントの本文: $BODY"
if [ "${1:-}" = "--dry-run" ]; then
  echo "shuhei1101/mdmark#478 へのコメント: changed"
  exit 0
fi

# 適用
if gh issue comment 478 -R shuhei1101/mdmark --body "$BODY" 2>/tmp/mdmark-478-comment.err; then
  echo "shuhei1101/mdmark#478 へのコメント: changed"
else
  echo "shuhei1101/mdmark#478 へのコメント: failed"
  echo "gh issue comment 478 -R shuhei1101/mdmark --body ..."
  cat /tmp/mdmark-478-comment.err
  exit 1
fi
