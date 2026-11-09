#!/usr/bin/env bash
# 普段使いのクローンの直下で叩く。.venv/ が uv.lock の版に揃い、作り直しより後に .venv の Python で起動したかを読むだけで確かめる
set -uo pipefail

LAUNCHER_LOG=/mnt/c/Users/shuhe/AppData/Local/voice-paste/log/launcher.log
FAILED=0

if uv.exe sync --frozen --check 2>&1; then
  echo ".venv と uv.lock: ok"
else
  echo ".venv と uv.lock: failed"
  FAILED=1
fi

if [ -f "$LAUNCHER_LOG" ] && [ "$LAUNCHER_LOG" -nt .venv/pyvenv.cfg ] \
  && grep -q '\.venv\\Scripts\\pythonw\.exe' "$LAUNCHER_LOG" \
  && grep -q 'launcher exited with code 0' "$LAUNCHER_LOG"; then
  echo "起動の記録: ok"
else
  echo "起動の記録: failed"
  FAILED=1
fi
cat "$LAUNCHER_LOG" 2> /dev/null

exit "$FAILED"
