"""VM の確認用: uinput の仮想のキーボードと絶対座標のポインタで、キーを押す・座標をクリックする。

使い方:
  vminput.py key ctrl+alt+d        # 組み合わせを押して離す
  vminput.py click 847 16          # 画面の座標（1024x768）を左クリック
"""

import sys
import time

from evdev import AbsInfo, UInput, ecodes as e

SCREEN_W, SCREEN_H = 1024, 768
KEYS = {
    "ctrl": e.KEY_LEFTCTRL,
    "alt": e.KEY_LEFTALT,
    "shift": e.KEY_LEFTSHIFT,
    "super": e.KEY_LEFTMETA,
    "esc": e.KEY_ESC,
    "escape": e.KEY_ESC,
    "enter": e.KEY_ENTER,
}


def key_code(name: str) -> int:
    """名前からキーのコードを返す。"""
    name = name.lower()
    return KEYS.get(name) or getattr(e, f"KEY_{name.upper()}")


def press(combo: str) -> None:
    """組み合わせを順に押し、逆順に離す。"""
    codes = [key_code(n) for n in combo.split("+")]
    with UInput({e.EV_KEY: list(KEYS.values()) + [getattr(e, f"KEY_{c}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]}, name="vm-check-keyboard") as ui:
        time.sleep(1.0)
        for code in codes:
            ui.write(e.EV_KEY, code, 1)
            ui.syn()
            time.sleep(0.05)
        for code in reversed(codes):
            ui.write(e.EV_KEY, code, 0)
            ui.syn()
            time.sleep(0.05)
        time.sleep(0.5)


def click(x: int, y: int) -> None:
    """絶対座標のポインタを x, y へ動かして左クリックする。"""
    caps = {
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
        e.EV_ABS: [
            (e.ABS_X, AbsInfo(0, 0, SCREEN_W - 1, 0, 0, 0)),
            (e.ABS_Y, AbsInfo(0, 0, SCREEN_H - 1, 0, 0, 0)),
        ],
        e.EV_REL: [e.REL_WHEEL],
    }
    with UInput(caps, name="vm-check-tablet") as ui:
        time.sleep(1.0)
        ui.write(e.EV_ABS, e.ABS_X, x)
        ui.write(e.EV_ABS, e.ABS_Y, y)
        ui.syn()
        time.sleep(0.3)
        ui.write(e.EV_KEY, e.BTN_LEFT, 1)
        ui.syn()
        time.sleep(0.1)
        ui.write(e.EV_KEY, e.BTN_LEFT, 0)
        ui.syn()
        time.sleep(0.5)


if __name__ == "__main__":
    if sys.argv[1] == "key":
        press(sys.argv[2])
    else:
        click(int(sys.argv[2]), int(sys.argv[3]))
