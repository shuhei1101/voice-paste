"""PoC: uinput の仮想キーボードで組み合わせのキーを押す（例: python keys.py LEFTMETA LEFTALT D）。"""
import sys, time
from evdev import UInput, ecodes
codes = [ecodes.ecodes[f"KEY_{k}"] for k in sys.argv[1:]]
ui = UInput(name="poc-keys")
time.sleep(0.5)
for c in codes: ui.write(ecodes.EV_KEY, c, 1)
ui.syn(); time.sleep(0.05)
for c in reversed(codes): ui.write(ecodes.EV_KEY, c, 0)
ui.syn()
print(f"pressed {time.time():.3f}")
time.sleep(0.3); ui.close()
