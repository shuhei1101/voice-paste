#!/usr/bin/env bash
# 使い方: poc217.sh {作業フォルダ} {出力フォルダ} {回}
set -u
source ~/vm_env.sh
DIR=$1; OUT=$2; N=$3
mkdir -p "$OUT"
pkill -f "python -m voice_paste"; sleep 3
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3 ~/.cache/huggingface/hub/blobs/28
cd "$DIR"
start=$(date +%s.%N)
./voice-paste.sh >/dev/null 2>&1
menu_done=0
for i in $(seq 1 30); do
  sleep 3
  t=$(python3 -c "import time;print(round(time.time()-$start))")
  size=$(du -s ~/.cache/huggingface/hub/blobs 2>/dev/null | cut -f1)
  echo "run$N ${t}s blobs_kb=$size" >> "$OUT/watch.txt"
  import -window root -crop 1024x32+0+0 "$OUT/run${N}_bar_${t}s.png"
  # 取得中（blobs が 2.9GB に届く前）に 1 回だけトレイのアイコンを押してメニューを撮る
  if [ $menu_done = 0 ] && [ "$t" -ge 9 ] && [ "${size:-0}" -lt 3000000 ]; then
    xdotool mousemove 847 16 click 1; sleep 1.5
    import -window root "$OUT/run${N}_menu_${t}s.png"
    xdotool key Escape; menu_done=1
  fi
done
grep -E "設定を読んだ|PoC|ワーカーが立ち上がった|常駐サービスを始めた" ~/.local/share/voice-paste/log/2026-11-01.log | tail -4 | cut -c1-200 >> "$OUT/watch.txt"
