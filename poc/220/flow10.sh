# PoC: 通しを 10 回（奇数はネイティブ、偶数は XWayland のプローブ）。確定は開始と同じ Super+Alt+D（貼り付けて送信）
for i in $(seq 1 10); do
  if [ $((i % 2)) -eq 1 ]; then P=wayland; else P=xcb; fi
  bash ~/vp-220/flow.sh $P D g10_$i > /tmp/g10_$i.log 2>&1 </dev/null
  h=$(cat ~/.local/share/voice-paste/history/*/*.txt)
  p=$(cat /tmp/probe_g10_$i.txt)
  k=$(grep -c "0x56 mods=0x4000000" /tmp/probe_g10_$i.keys)
  if [ "$p" = "$h" ] && grep -q $'\n' /tmp/probe_g10_$i.txt; then r=OK; else r=NG; fi
  echo "$i $P $r ctrlv=[$k] probe=$(cat /tmp/probe_g10_$i.txt | od -c | tail -2 | head -1)"
done
