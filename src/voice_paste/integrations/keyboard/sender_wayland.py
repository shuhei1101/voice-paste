"""Wayland の貼り付けのキーと Enter の送信。python-evdev の UInput の仮想キーボードでキーを送信する。"""

from __future__ import annotations

import logging
import time

from evdev import UInput, ecodes

from voice_paste.integrations.keyboard.sender import split_paste_key
from voice_paste.shared.errors import DeliveryError

logger = logging.getLogger(__name__)

CLIPBOARD_FOCUS_SETTLE_SEC: float = 0.3
"""貼り付けのキーを送信する前に待つ秒数。GNOME の wl-copy はクリップボードへ書くときに一瞬フォーカスを取るため、貼り付け先へ戻るのを待つ。"""

DEVICE_READY_SEC: float = 0.3
"""仮想キーボードを作ってから、コンポジターが入力の機器として受け付けるまで待つ時間。"""

MODIFIER_CODES: dict[str, int] = {
    "ctrl": ecodes.KEY_LEFTCTRL,
    "shift": ecodes.KEY_LEFTSHIFT,
    "alt": ecodes.KEY_LEFTALT,
    "cmd": ecodes.KEY_LEFTMETA,
}
"""pynput の書式の修飾キーの名前と、evdev のキーコードの対応。"""

_device: UInput | None = None


def _get_device() -> UInput:
    """仮想キーボードを 1 回だけ作って返す。"""
    global _device  # noqa: PLW0603 PoC
    if _device is None:
        _device = UInput(name="voice-paste-keyboard")
        time.sleep(DEVICE_READY_SEC)
    return _device


def _modifier_code(modifier: object) -> int:
    """pynput の修飾キー（Key.ctrl など）か名前を evdev のキーコードに替える。"""
    name = getattr(modifier, "name", str(modifier)).strip("<>").removesuffix("_l")
    if name not in MODIFIER_CODES:
        raise DeliveryError(f"送信できない修飾キーです（{modifier}）")
    return MODIFIER_CODES[name]


def _tap(modifiers: list[int], main: int) -> None:
    """修飾キーを押し、主キーを押して離し、修飾キーを逆順に離す。"""
    device = _get_device()
    for code in modifiers:
        device.write(ecodes.EV_KEY, code, 1)
    device.write(ecodes.EV_KEY, main, 1)
    device.write(ecodes.EV_KEY, main, 0)
    for code in reversed(modifiers):
        device.write(ecodes.EV_KEY, code, 0)
    device.syn()


def send_paste_wayland(paste_key: str) -> None:
    """設定の貼り付けのキーを仮想キーボードで送信する。"""
    modifiers, main_key = split_paste_key(paste_key)
    time.sleep(CLIPBOARD_FOCUS_SETTLE_SEC)
    _tap([_modifier_code(m) for m in modifiers], ecodes.ecodes[f"KEY_{main_key.upper()}"])
    logger.info(f"貼り付けのキーを送信した（{paste_key}、uinput）")


def send_enter_wayland(modifiers: list[str]) -> None:
    """Enter を、修飾キー（ctrl / shift）つきで仮想キーボードで送信する。"""
    _tap([_modifier_code(m) for m in modifiers], ecodes.KEY_ENTER)
    logger.info(f"Enter を送信した（{'+'.join([*modifiers, 'enter'])}、uinput）")
