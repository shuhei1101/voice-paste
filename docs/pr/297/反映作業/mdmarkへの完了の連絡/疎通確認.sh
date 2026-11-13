#!/bin/sh
set -eu

if gh issue view 478 -R shuhei1101/mdmark --json state --jq .state >/dev/null 2>/tmp/mdmark-478-ping.err; then
  echo "shuhei1101/mdmark#478 の読み取り: ok"
else
  echo "shuhei1101/mdmark#478 の読み取り: failed"
  echo "gh issue view 478 -R shuhei1101/mdmark --json state"
  cat /tmp/mdmark-478-ping.err
  exit 1
fi
if gh pr view 297 -R shuhei1101/voice-paste --json state --jq .state >/dev/null 2>/tmp/voice-paste-297-ping.err; then
  echo "shuhei1101/voice-paste#297 の読み取り: ok"
else
  echo "shuhei1101/voice-paste#297 の読み取り: failed"
  echo "gh pr view 297 -R shuhei1101/voice-paste --json state"
  cat /tmp/voice-paste-297-ping.err
  exit 1
fi
