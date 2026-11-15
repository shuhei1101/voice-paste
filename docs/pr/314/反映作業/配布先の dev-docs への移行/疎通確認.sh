#!/bin/sh
set -eu

REPO="${1:-}"
if [ -z "$REPO" ] || ! git -C "$REPO" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "対象のリポジトリ: failed"
  exit 1
fi
echo "対象のリポジトリ: ok"
if [ -r "$HOME/.config/dev-docs/settings.yaml" ]; then
  echo "dev-docs の端末の設定: ok"
else
  echo "dev-docs の端末の設定: failed"
  exit 1
fi
if [ -r "$HOME/.config/ai-monitor/settings.yaml" ]; then
  echo "AI Monitor の共通設定: ok"
else
  echo "AI Monitor の共通設定: failed"
  exit 1
fi
