source ~/vm_env_wayland.sh; cd ~/vp-220
systemd-run --user --unit vp220a --collect bash -c ". ~/vm_env_wayland.sh; export QT_QPA_PLATFORM=xcb; cd ~/vp-220; exec .venv/bin/python -m voice_paste > /tmp/vp220a.out 2>&1"
sleep 25
systemd-run --user --unit vp220 --collect bash -c ". ~/vm_env_wayland.sh; export QT_QPA_PLATFORM=xcb; cd ~/vp-220; exec .venv/bin/python -m voice_paste > /tmp/vp220.out 2>&1"
sleep 25
echo "== first"; grep -E "ショートカット|終わ|片付け" /tmp/vp220a.out | tail -3 | cut -c1-160
echo "== second"; grep -E "頼んだ|ショートカット|常駐サービスを始めた" /tmp/vp220.out | tail -4 | cut -c1-160
systemctl --user is-active vp220a vp220
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings | tr ',' '\n' | wc -l
