#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。作った .venv/ を .venv.failed/ へ移して残し、.venv を残した venv/ へのジャンクションにして、起動のバッチファイルで起動し直す
# 実行を流し直す前に、ジャンクションの .venv を cmd.exe /c rmdir .venv で外す（実行の前提確認がジャンクションの .venv を止める）
set -uo pipefail

if [ ! -f venv/Scripts/pythonw.exe ]; then
  echo "残した venv: failed"
  exit 1
fi
echo "残した venv: ok"

if [ -L .venv ]; then
  echo ".venv の退避: skipped"
elif [ -e .venv.failed ]; then
  echo ".venv の退避: failed"
  exit 1
elif [ -d .venv ]; then
  if ! mv .venv .venv.failed; then
    echo ".venv の退避: failed"
    exit 1
  fi
  echo ".venv の退避: changed"
else
  echo ".venv の退避: skipped"
fi

if [ -L .venv ]; then
  echo "venv へのジャンクション: skipped"
elif cmd.exe /c 'mklink /J .venv venv' > /dev/null; then
  echo "venv へのジャンクション: changed"
else
  echo "venv へのジャンクション: failed"
  exit 1
fi

if ! cmd.exe /c voice-paste.bat; then
  echo "venv での起動し直し: failed"
  exit 1
fi
echo "venv での起動し直し: changed"
