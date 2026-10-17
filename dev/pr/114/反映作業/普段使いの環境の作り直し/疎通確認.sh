#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。環境を作る Windows の uv と、起動のバッチファイル・ロックへ読み取りだけでつながるかを確かめる
set -uo pipefail

FAILED=0

if uv.exe --version > /dev/null 2>&1; then
  echo "Windows の uv: ok"
else
  echo "Windows の uv: failed"
  FAILED=1
fi

if [ -f uv.lock ] && [ -f .python-version ]; then
  echo "uv.lock と .python-version: ok"
else
  echo "uv.lock と .python-version: failed"
  FAILED=1
fi

if grep -q '\.venv\\Scripts\\pythonw\.exe' voice-paste.bat 2> /dev/null; then
  echo "起動のバッチファイル: ok"
else
  echo "起動のバッチファイル: failed"
  FAILED=1
fi

if cmd.exe /c ver > /dev/null 2>&1; then
  echo "Windows のコマンドプロンプト: ok"
else
  echo "Windows のコマンドプロンプト: failed"
  FAILED=1
fi

exit "$FAILED"
