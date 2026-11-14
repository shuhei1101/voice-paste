#!/bin/sh
set -eu

REPO="${1:-}"
if [ -z "$REPO" ] || [ ! -f "$REPO/dev-docs.yaml" ]; then
  echo "dev-docs.yaml: failed"
  exit 1
fi
NAME=$(sed -n 's/^name: *//p' "$REPO/dev-docs.yaml" | head -n 1)
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8781/$NAME@develop/")
if [ "$code" = "200" ]; then
  echo "dev-docs の画面の /$NAME@develop/: ok（$code）"
else
  echo "dev-docs の画面の /$NAME@develop/: failed（$code）"
  exit 1
fi
