#!/usr/bin/env bash
# 引数: 対象（terminal / native / xwayland）
set -u
source ~/vm_env_w.sh
T=$1; OUT=/tmp/p223; mkdir -p $OUT
pkill -f "[p]robe.py"; pkill -f "[g]nome-terminal-server"; sleep 1
case $T in
  terminal) rm -f $OUT/term.txt; touch $OUT/term.txt
    setsid gnome-terminal -- bash -c "stty -icanon -echo; cat > $OUT/term.txt" >/dev/null 2>&1 </dev/null ; F=$OUT/term.txt ;;
  native)   QT_QPA_PLATFORM=wayland setsid ~/vp-220/.venv/bin/python ~/vp-220/probe.py $OUT/native.txt >/dev/null 2>&1 </dev/null & F=$OUT/native.txt ;;
  xwayland) QT_QPA_PLATFORM=xcb setsid ~/vp-220/.venv/bin/python ~/vp-220/probe.py $OUT/xwayland.txt >/dev/null 2>&1 </dev/null & F=$OUT/xwayland.txt ;;
esac
sleep 3
cd ~/vp-238
PYTHONPATH=src .venv/bin/python ~/paste223.py $F $T > $OUT/${T}_${2:-on}.log 2>&1 </dev/null; grep -v onnx $OUT/${T}_${2:-on}.log
gnome-screenshot -f $OUT/${T}_${2:-on}.png
