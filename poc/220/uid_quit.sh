source ~/vm_env_wayland.sh; cd ~/vp-220
NAME=$(grep -o "単一インスタンスを確保した（[^）]*" /tmp/vp220.out | tail -1 | sed "s/.*（//")
echo "== other uid ($NAME)"
sudo -u nobody python3 -c "
import socket; s=socket.socket(socket.AF_UNIX); s.connect('\0$NAME-quit'); s.sendall(b'hotkey:<alt>+<cmd>+j'); s.close(); print('sent as nobody')"
sleep 1
grep -E "ホットキーを受けた|録音を始めた" /tmp/vp220.out | tail -1 | cut -c1-160
echo "== tray quit"
ITEM=$(gdbus call --session -d org.kde.StatusNotifierWatcher -o /StatusNotifierWatcher -m org.freedesktop.DBus.Properties.Get org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems | grep -oE "':[0-9.]+@/StatusNotifierItem'" | tr -d "'")
gdbus call --session -d ${ITEM%@*} -o /MenuBar -m com.canonical.dbusmenu.Event -- 1 clicked "<''>" 0
sleep 4
pgrep -f "python -m voice_paste" || echo "service exited"
grep -E "ショートカット" /tmp/vp220.out | tail -1 | cut -c1-160
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
sed -i 's/^start = "<alt>+<cmd>+j"/start = "<cmd>+<alt>+d"/' ~/.config/voice-paste/settings.toml; grep "^start" ~/.config/voice-paste/settings.toml
