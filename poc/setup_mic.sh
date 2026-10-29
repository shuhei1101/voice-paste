#!/usr/bin/env bash
# PipeWire の仮想マイクを作り、既定の入力にする（PoC）
set -eu
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
FIFO=/tmp/vp-mic.fifo
pactl unload-module module-pipe-source 2>/dev/null || true
rm -f "$FIFO"
pactl load-module module-pipe-source source_name=vp_mic file="$FIFO" format=s16le rate=16000 channels=1
pactl set-default-source vp_mic
pactl get-default-source
