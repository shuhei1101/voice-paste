source ~/vm_env_wayland.sh; cd ~/vp-220
echo "== copy_only"
bash ~/vp-220/flow.sh wayland C copy > /tmp/copy.log 2>&1 </dev/null
echo "probe after copy_only: [$(cat /tmp/probe_copy.txt)]"
echo "== stop service"
systemctl --user stop vp220; sleep 2
journalctl --user -u vp220 --since "-1min" --no-pager | tail -3
grep -E "ショートカットを外した|終了|止め" /tmp/vp220.out | tail -3 | cut -c1-200
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
echo "== paste after stop"
pkill -f "[p]robe.py"; sleep 1
setsid .venv/bin/python probe.py /tmp/after.txt >/dev/null 2>&1 </dev/null & sleep 3
.venv/bin/python keys.py LEFTCTRL V; sleep 1
echo "probe: [$(cat /tmp/after.txt)]"
echo "== stale hotkey after stop"
.venv/bin/python keys.py LEFTMETA LEFTALT D; sleep 1
echo "keys: $(cat /tmp/after.keys | tr '\n' '|')"
pgrep -af "[s]end_hotkey" || echo "no send_hotkey left"
pkill -f "[p]robe.py"
