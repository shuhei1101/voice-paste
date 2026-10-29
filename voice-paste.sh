#!/usr/bin/env bash
set -euo pipefail

# スクリプトの場所（リポジトリの直下）へ移る
cd "$(dirname "$0")"

# 起動の記録: 起動のたびに上書きする（アプリは日付つきのログを自分で消す）
LOG_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/voice-paste/log"
mkdir -p "$LOG_DIR"
LAUNCHER_LOG="$LOG_DIR/launcher.log"
PYTHON=".venv/bin/python"

log() {
    echo "[$(date -Iseconds)] $*" >> "$LAUNCHER_LOG"
}

# 環境を作れないときの終わり方: 理由と記録の場所を標準エラーに出し、端末が無ければ通知する
fail() {
    local code="$1" message="$2"
    log "$message"
    echo "$message" >&2
    echo "See log: $LAUNCHER_LOG" >&2
    # 標準エラーが端末でなく（自動起動・アプリの一覧）notify-send があるときは、同じ 2 行を通知する
    if [ ! -t 2 ] && command -v notify-send > /dev/null 2>&1; then
        notify-send "voice-paste" "$message
See log: $LAUNCHER_LOG" || true
    fi
    exit "$code"
}

: > "$LAUNCHER_LOG"
log "voice-paste.sh start"
log "cwd=$PWD"

# uv: PATH を先に探し、無ければ既定の置き場所を使う
UV=""
if command -v uv > /dev/null 2>&1; then
    UV="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
fi

if [ -n "$UV" ]; then
    log "uv: $UV"
    echo "Syncing .venv with uv sync --frozen. See log: $LAUNCHER_LOG"
    log "running: uv sync --frozen --extra local-whisper"
    sync_code=0
    "$UV" sync --frozen --extra local-whisper >> "$LAUNCHER_LOG" 2>&1 || sync_code=$?
    log "uv sync --frozen exited with code $sync_code"
    if [ "$sync_code" -ne 0 ]; then
        fail "$sync_code" "[ERROR] uv sync --frozen failed with code $sync_code."
    fi
else
    log "uv not found, skipping uv sync"
fi

# .venv から voice_paste を import できるか（.venv や python の有無では判定しない）
import_code=0
"$PYTHON" -c "import voice_paste" >> "$LAUNCHER_LOG" 2>&1 || import_code=$?
log "import voice_paste from .venv exited with code $import_code"
if [ "$import_code" -ne 0 ]; then
    if [ -z "$UV" ]; then
        fail 1 "[ERROR] uv not found. Install uv and run voice-paste.sh again."
    fi
    fail 1 "[ERROR] voice_paste cannot be imported from .venv after uv sync."
fi

log "python: $("$PYTHON" -c 'import sys; print(sys.executable, sys.version.split()[0])')"

# 端末から切り離して常駐サービスを起動する（標準入出力は捨てる）
log "launching: $PYTHON -m voice_paste $*"
launch_code=0
setsid -f "$PYTHON" -m voice_paste "$@" < /dev/null > /dev/null 2>&1 || launch_code=$?
log "launcher exited with code $launch_code"
if [ "$launch_code" -ne 0 ]; then
    fail "$launch_code" "[ERROR] failed to launch voice_paste with code $launch_code"
fi
