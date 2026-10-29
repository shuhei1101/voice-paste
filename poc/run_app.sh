#!/usr/bin/env bash
# PoC: Xorg のセッションの環境変数を揃え、常駐サービスを端末から切り離して起動する
set -eu
cd "$(dirname "$0")/.."
export DISPLAY=:0
export XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export HF_HOME="${HF_HOME:-/tmp/vp-hf}"
DATA_DIR="${DATA_DIR:-/tmp/vp-data}"
mkdir -p "$DATA_DIR"
date -Is > "$DATA_DIR/started_at"
setsid .venv/bin/python -m voice_paste --data-dir "$DATA_DIR" > "$DATA_DIR/stdout.log" 2>&1 < /dev/null &
echo $! > "$DATA_DIR/pid"
