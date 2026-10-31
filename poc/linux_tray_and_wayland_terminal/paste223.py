"""PoC #223: copy → 送信を 10 回行い、貼り付け先のファイルの中身と比べる。引数: 貼り付け先のファイル、ラベル"""
import logging, sys, time
from pathlib import Path
from voice_paste.integrations.keyboard.sender import copy_to_clipboard
from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard

logging.basicConfig(level=logging.INFO, format="%(message)s")
out = Path(sys.argv[1]); label = sys.argv[2]
kb = UInputKeyboard(); kb.open(); time.sleep(1.0)
expected = ""; ok = 0
for i in range(1, 11):
    text = f"[{label}{i}]"
    copy_to_clipboard(text)
    try:
        kb.send_paste("<ctrl>+v")
    except Exception as error:  # noqa: BLE001
        print(i, "ERROR", error)
    expected += text
    time.sleep(0.6)
    got = out.read_text(encoding="utf-8") if out.exists() else ""
    r = got == expected
    ok += r
    print(i, "OK" if r else f"NG got={got!r}")
print(f"{label}: {ok}/10")
kb.close()
