source ~/vm_env_wayland.sh; cd ~/vp-220
.venv/bin/python tap.py 767 49; sleep 2
grep -E "ショートカット" /tmp/vp220.out | tail -2 | cut -c1-240
for p in $(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings | tr -d "[]',"); do
  echo "$p $(gsettings get org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$p binding)"
done
echo "== old key D"
.venv/bin/python keys.py LEFTMETA LEFTALT D; sleep 1.5
grep -E "ホットキーを受けた|録音を始めた" /tmp/vp220.out | tail -1 | cut -c1-200
echo "== new key J"
.venv/bin/python keys.py LEFTMETA LEFTALT J; sleep 1.5
grep -E "ホットキーを受けた|録音を始めた" /tmp/vp220.out | tail -2 | cut -c1-200
.venv/bin/python keys.py LEFTMETA LEFTALT Q; sleep 1
grep -E "取り消した" /tmp/vp220.out | tail -1 | cut -c1-200
