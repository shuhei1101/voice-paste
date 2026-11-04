#!/usr/bin/env bash
# 使い方: run217.sh {x|w} {出力フォルダ}
# 既定のモデル large-v3 をキャッシュから削除して起動し、取得中のバーとメニュー、待機中のバー、ホットキーで始めた録音を撮る。
set -u
S=$1; OUT=$2
if [ "$S" = x ]; then source ~/vm_env.sh; else source ~/vm_env_w.sh; fi
mkdir -p "$OUT"; rm -f "$OUT"/*
shot() { if [ "$S" = x ]; then import -window root "$1"; else gnome-screenshot -f "$1"; fi; }
clickat() { if [ "$S" = x ]; then xdotool mousemove "$1" "$2" click 1; else ~/vp-238/.venv/bin/python ~/vm238/vminput.py click "$1" "$2"; fi; }
keys() { if [ "$S" = x ]; then xdotool key "$1"; else ~/vp-238/.venv/bin/python ~/vm238/vminput.py key "$1"; fi; }
LOGDIR=~/.local/share/voice-paste/log
pkill -f "[p]ython -m voice_paste"; sleep 3
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3 ~/.cache/huggingface/hub/blobs/28*
before=$(cat $LOGDIR/*.log 2>/dev/null | wc -l)
echo "session=$S XDG_SESSION_TYPE=$(loginctl show-session $(loginctl | awk '/seat0/{print $1}') -p Type --value) commit=$(cat ~/vp-238/DEPLOYED_COMMIT)" > "$OUT/watch.txt"
# アクティビティの画面が開いていれば閉じる
clickat 545 410; sleep 1.5
cd ~/vp-238
start=$(date +%s)
./voice-paste.sh >/dev/null 2>&1
menu_done=0
for i in $(seq 1 60); do
  sleep 3
  t=$(( $(date +%s) - start ))
  size=$(du -s ~/.cache/huggingface/hub/blobs 2>/dev/null | cut -f1)
  started=$(cat $LOGDIR/*.log | tail -n +$((before+1)) | grep -c "常駐サービスを始めた")
  failed=$(cat $LOGDIR/*.log | tail -n +$((before+1)) | grep -c "起動に失敗")
  echo "${t}s blobs_kb=$size started=$started failed=$failed" >> "$OUT/watch.txt"
  if [ $menu_done = 0 ] && [ "$t" -ge 9 ] && [ "$started" = 0 ]; then
    shot "$OUT/downloading_${t}s.png"
    clickat 847 16; sleep 1.5
    shot "$OUT/downloading_menu_${t}s.png"
    keys Escape; menu_done=1
  fi
  if [ "$started" -ge 1 ] || [ "$failed" -ge 1 ]; then break; fi
done
sleep 3
shot "$OUT/ready.png"
keys super+alt+d; sleep 3
shot "$OUT/recording.png"
keys super+alt+q; sleep 2
shot "$OUT/cancelled.png"
cat $LOGDIR/*.log | tail -n +$((before+1)) | grep -E "取得|ワーカー|常駐サービスを始めた|起動に失敗|録音|取り消|ERROR" | cut -c1-220 >> "$OUT/watch.txt"
du -sh ~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3 >> "$OUT/watch.txt" 2>&1
