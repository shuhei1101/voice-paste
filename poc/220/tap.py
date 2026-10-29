"""PoC: uinput のペンタブレットで画面の座標（1024x768 の論理座標）をタップする（例: python tap.py 848 16 740 167。座標の組を続けて同じ機器でタップする）。"""
import sys, time
from evdev import AbsInfo, UInput, ecodes as e
W, H = 1024, 768
pts = [(int(sys.argv[i]), int(sys.argv[i + 1])) for i in range(1, len(sys.argv), 2)]
cap = {
    e.EV_KEY: [e.BTN_TOOL_PEN, e.BTN_TOUCH, e.BTN_STYLUS],
    e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, W - 1, 0, 0, 10)), (e.ABS_Y, AbsInfo(0, 0, H - 1, 0, 0, 10)),
               (e.ABS_PRESSURE, AbsInfo(0, 0, 255, 0, 0, 0))],
}
ui = UInput(cap, name="poc-pen", input_props=[e.INPUT_PROP_DIRECT])
time.sleep(0.8)
def ev(t, c, v): ui.write(t, c, v)
for x, y in pts:
    ev(e.EV_ABS, e.ABS_X, x); ev(e.EV_ABS, e.ABS_Y, y); ev(e.EV_KEY, e.BTN_TOOL_PEN, 1); ui.syn(); time.sleep(0.15)
    ev(e.EV_KEY, e.BTN_TOUCH, 1); ev(e.EV_ABS, e.ABS_PRESSURE, 200); ui.syn(); time.sleep(0.08)
    ev(e.EV_KEY, e.BTN_TOUCH, 0); ev(e.EV_ABS, e.ABS_PRESSURE, 0); ui.syn(); time.sleep(0.1)
    ev(e.EV_KEY, e.BTN_TOOL_PEN, 0); ui.syn(); time.sleep(1.2)
ui.close()
