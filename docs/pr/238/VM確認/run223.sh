#!/usr/bin/env bash
# 使い方: run223.sh {ラベル（on / off）} {出力フォルダ}
# Wayland のセッションで GNOME Terminal を前面にし、ホットキーで録音して読み上げの WAV を流し、「貼り付けのみ」で確定する。
set -u
source ~/vm_env_w.sh
L=$1; OUT=$2
mkdir -p "$OUT"
keys() { ~/vp-238/.venv/bin/python ~/vm238/vminput.py key "$1"; }
LOGDIR=~/.local/share/voice-paste/log
before=$(cat $LOGDIR/*.log | wc -l)
echo "label=$L commit=$(cat ~/vp-238/DEPLOYED_COMMIT) extension=$(gnome-extensions info focused-window-dbus@flexagoon.com | grep "状態")" > "$OUT/${L}_result.txt"
pkill -f "[g]nome-terminal-server"; sleep 1
rm -f "$OUT/${L}_term.txt"; touch "$OUT/${L}_term.txt"
setsid gnome-terminal -- bash -c "stty -icanon; cat > $OUT/${L}_term.txt" >/dev/null 2>&1 </dev/null
sleep 3
keys super+alt+d; sleep 1.5
paplay --device=auto_null ~/vm238/speech.wav
sleep 1
gnome-screenshot -f "$OUT/${L}_recording.png"
keys super+alt+v
for i in $(seq 1 60); do
  sleep 2
  if cat $LOGDIR/*.log | tail -n +$((before+1)) | grep -qE "セッションを終えた|結果が空|ERROR|失敗"; then break; fi
done
sleep 2
gnome-screenshot -f "$OUT/${L}_terminal.png"
{
  echo "--- 端末へ入った文字（od）"; od -c "$OUT/${L}_term.txt" | head -20
  echo "--- 端末へ入った文字"; cat "$OUT/${L}_term.txt"; echo
  echo "--- クリップボード（wl-paste）"; timeout 5 wl-paste 2>&1; echo; echo "--- クリップボード（XWayland の xclip）"; timeout 5 xclip -o -selection clipboard 2>&1
  echo "--- ログ"; cat $LOGDIR/*.log | tail -n +$((before+1)) | cut -c1-260
} >> "$OUT/${L}_result.txt"
pkill -f "[g]nome-terminal-server"
