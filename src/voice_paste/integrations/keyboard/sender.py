"""クリップボードへの書き込みと、今のアクティブなウィンドウへのキー入力。pyperclip に触れるのはこのファイルだけ。pynput はこのファイルと sender_linux.py が触れる。"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import pyperclip
from pynput import keyboard

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import EnterModifier

logger = logging.getLogger(__name__)

FOCUS_SETTLE_SEC: float = 0.1
"""貼り付けのキーを送信する前に待つ秒数。貼り付け先のフォーカスが落ち着くのを待つ。"""

KEY_SEPARATOR: str = "+"
"""貼り付けのキーの書式（pynput の GlobalHotKeys の書式）で、キーを区切る文字。"""

MODIFIER_KEYS: dict[str, keyboard.Key] = {
    "<ctrl>": keyboard.Key.ctrl,
    "<shift>": keyboard.Key.shift,
    "<alt>": keyboard.Key.alt,
    "<cmd>": keyboard.Key.cmd,
    "<win>": keyboard.Key.cmd,
}
"""貼り付けのキーの書式の修飾キーと、押す pynput のキー。"""

ENTER_MODIFIER_KEYS: dict[EnterModifier, keyboard.Key] = {
    "ctrl": keyboard.Key.ctrl,
    "alt": keyboard.Key.alt,
    "shift": keyboard.Key.shift,
}
"""Enter と一緒に押す修飾キーと、押す pynput のキー。並びが押す順（Ctrl・Alt・Shift）。"""


def copy_to_clipboard(text: str) -> None:
    """pyperclip でクリップボードへ書く。書けなければ DeliveryError にする。"""
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as error:
        raise DeliveryError(f"クリップボードへ書けませんでした（{error}）") from error
    logger.info(f"クリップボードへ書いた（{len(text)} 文字）")


def split_paste_key(paste_key: str) -> tuple[list[keyboard.Key], str]:
    """設定の貼り付けのキーを、押す修飾キー（貼り付けのキーの並び）と、小文字にした主キーに分ける。主キーが 1 つでなければ DeliveryError にする。"""
    # 1. 貼り付けのキーを、前後の空白を除いて小文字にしたキーに区切る
    tokens = [token.strip().lower() for token in paste_key.split(KEY_SEPARATOR)]

    # 2. 修飾キーとそれ以外（主キー）に分ける
    modifiers = [MODIFIER_KEYS[token] for token in tokens if token in MODIFIER_KEYS]
    main_keys = [token for token in tokens if token not in MODIFIER_KEYS]
    if len(main_keys) != 1:
        raise DeliveryError(f"貼り付けのキーに主キーが 1 つありません（{paste_key}）")
    return modifiers, main_keys[0]


def send_paste(paste_key: str) -> None:
    """設定の貼り付けのキーを、フォーカスが落ち着くのを待ってから今のアクティブなウィンドウへ送信する。主キーは文字のまま渡す（Windows の送り方）。"""
    # 1. 貼り付けのキーを修飾キーと主キーに分ける
    modifiers, main_key = split_paste_key(paste_key)

    # 2. 貼り付け先のフォーカスが落ち着くのを待つ
    time.sleep(FOCUS_SETTLE_SEC)

    # 3. 修飾キーを順に押し、主キーを押して離し、修飾キーを逆順に離す
    controller = keyboard.Controller()
    for modifier in modifiers:
        controller.press(modifier)
    controller.press(main_key)
    controller.release(main_key)
    for modifier in reversed(modifiers):
        controller.release(modifier)
    logger.info(f"貼り付けのキーを送信した（{paste_key}）")


def send_enter(modifiers: Sequence[EnterModifier] = ()) -> None:
    """渡した修飾キーを押したまま Enter を押して離す（修飾キーが無ければ Enter だけ）。待ちは呼ぶ側が置く。"""
    # 1. 修飾キーを Ctrl・Alt・Shift の並びに揃え、重なりを除く
    ordered = [modifier for modifier in ENTER_MODIFIER_KEYS if modifier in modifiers]

    # 2. 修飾キーを順に押し、Enter を押して離す
    controller = keyboard.Controller()
    pressed: list[keyboard.Key] = []
    try:
        for modifier in ordered:
            controller.press(ENTER_MODIFIER_KEYS[modifier])
            pressed.append(ENTER_MODIFIER_KEYS[modifier])
        controller.press(keyboard.Key.enter)
        controller.release(keyboard.Key.enter)
    finally:
        # 途中で失敗しても、押した修飾キーは逆順に離す（押されたままにしない）
        for key in reversed(pressed):
            controller.release(key)
    logger.info(f"Enter を送信した（修飾キー: {'+'.join(ordered) or 'なし'}）")
