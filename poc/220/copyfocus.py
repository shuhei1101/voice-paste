"""PoC: copy だけを 5 回行い、プローブのフォーカスの出入りを見る。"""
import time
from voice_paste.integrations.keyboard.sender import copy_to_clipboard
for i in range(5):
    t = time.time(); copy_to_clipboard(f"c{i}"); print(f"copy {t:.3f}"); time.sleep(1)
