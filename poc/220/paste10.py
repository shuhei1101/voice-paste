"""PoC: copy → 貼り付けのキーを 10 回送信し、プローブの中身と比べる。続けて Enter・Ctrl+Enter・Shift+Enter を送信する。"""
import sys, time
from pathlib import Path
from voice_paste.integrations.keyboard.sender import copy_to_clipboard
from voice_paste.integrations.keyboard.sender_wayland import send_paste_wayland, send_enter_wayland
out = Path(sys.argv[1])
expected = ""
for i in range(1, 11):
    text = f"貼り付け{i}回目。"
    copy_to_clipboard(text)
    send_paste_wayland("<ctrl>+v")
    expected += text
    time.sleep(0.4)
    got = out.read_text(encoding="utf-8")
    print(i, "OK" if got == expected else f"NG got={got!r}")
keys = out.with_suffix(".keys")
keys.write_text("", encoding="utf-8")
for mods in ([], ["ctrl"], ["shift"]):
    send_enter_wayland(mods)
    time.sleep(0.4)
print("keys:", keys.read_text(encoding="utf-8").strip().replace("\n", " | "))
