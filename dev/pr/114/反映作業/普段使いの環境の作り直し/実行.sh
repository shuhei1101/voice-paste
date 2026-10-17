#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。Windows の uv で .venv/ を uv.lock の版に揃え、起動のバッチファイルから起動し直す
# 今の venv/ には触れない（切り戻しで使う）
set -uo pipefail

# 前提確認
if ! uv.exe --version > /dev/null 2>&1 || [ ! -f uv.lock ] || [ ! -f .python-version ] \
  || ! grep -q '\.venv\\Scripts\\pythonw\.exe' voice-paste.bat; then
  echo "前提確認: failed"
  exit 1
fi
echo "前提確認: ok"

# 計画（--dry-run もここを通る）
if uv.exe sync --frozen --check 2>&1; then
  echo ".venv の作成: skipped"
  exit 0
fi
if [ "${1:-}" = "--dry-run" ]; then
  echo ".venv の作成: changed"
  echo "常駐アプリの起動し直し: changed"
  exit 0
fi

# 適用
if ! uv.exe sync --frozen; then
  echo ".venv の作成: failed"
  exit 1
fi
echo ".venv の作成: changed"

# 起動のバッチファイルは、動いている前の常駐アプリに終了を頼んでから新しく立てる
if ! cmd.exe /c voice-paste.bat; then
  echo "常駐アプリの起動し直し: failed"
  exit 1
fi
echo "常駐アプリの起動し直し: changed"
