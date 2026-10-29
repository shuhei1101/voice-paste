#!/usr/bin/env bash
# PoC: テキストエディターを前に出し、ホットキーで録音 → 仮想マイクへ WAV → 確定 → 貼り付けまでを流して撮る
set -eu
cd "$(dirname "$0")/.."
export DISPLAY=:0
export XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority"
OUT="${OUT:-/tmp/vp-flow}"
mkdir -p "$OUT"
win="${WIN:-$(xdotool search --class gnome-text-editor | tail -1)}"
xdotool windowactivate --sync "$win"
sleep 1
date +%s.%N > "$OUT/t_start"
xdotool key --clearmodifiers "${START_KEY:-ctrl+alt+d}"
sleep 1.5
import -window root "$OUT/10_recording.png"
.venv/bin/python poc/feed_mic.py poc/speech.wav --lead-silence-sec 0.5 --tail-silence-sec 1.0
import -window root "$OUT/11_recording_end.png"
date +%s.%N > "$OUT/t_confirm"
xdotool key --clearmodifiers ctrl+alt+v
sleep 1
import -window root "$OUT/12_transcribing.png"
for i in $(seq 1 120); do
  # 履歴に起こした文字のファイルができたら、届け終えたものとして扱う
  if compgen -G "/tmp/vp-data/history/*/*.txt" > /dev/null; then break; fi
  sleep 0.5
done
date +%s.%N > "$OUT/t_done"
sleep 1
import -window root "$OUT/13_pasted.png"
