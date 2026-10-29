#!/usr/bin/env bash
# PoC: 通し（ホットキー → 録音 → 確定 → 文字起こし → プローブへの貼り付け）。引数: プローブの QT_QPA_PLATFORM（wayland / xcb）、確定のキー（V / D / C）、出力の接頭辞
set -eu
source ~/vm_env_wayland.sh
cd ~/vp-220
PLAT=$1; KEY=$2; TAG=$3
OUT=/tmp/vp220shots; mkdir -p $OUT
pkill -f "[p]robe.py" 2>/dev/null || true; sleep 1
QT_QPA_PLATFORM=$PLAT setsid .venv/bin/python probe.py /tmp/probe_$TAG.txt >/dev/null 2>&1 < /dev/null &
sleep 3
rm -rf ~/.local/share/voice-paste/history
.venv/bin/python keys.py LEFTMETA LEFTALT D
sleep 1.5
gnome-screenshot -f $OUT/${TAG}_10_recording.png
.venv/bin/python tests/support/feed_mic.py ~/vp-poc/poc/speech.wav --lead-silence-sec 0.5 --tail-silence-sec 1.0
.venv/bin/python keys.py LEFTMETA LEFTALT $KEY
sleep 1.5
gnome-screenshot -f $OUT/${TAG}_12_transcribing.png
for i in $(seq 1 240); do
  if compgen -G "$HOME/.local/share/voice-paste/history/*/*.txt" > /dev/null; then break; fi
  sleep 0.5
done
sleep 3
gnome-screenshot -f $OUT/${TAG}_13_pasted.png
echo "history:"; cat ~/.local/share/voice-paste/history/*/*.txt; echo
echo "probe:"; cat /tmp/probe_$TAG.txt; echo
