"""クリップボードへの書き込みと、今のアクティブなウィンドウへのキー入力。pyperclip・pynput に触れるのはこのファイルだけ。"""

from __future__ import annotations

import logging
import time

import pyperclip
from pynput import keyboard

from voice_paste.shared.errors import DeliveryError

logger = logging.getLogger(__name__)

FOCUS_SETTLE_SEC: float = 0.1
"""貼り付けのキーを送る前に待つ秒数。貼り付け先のフォーカスが落ち着くのを待つ。"""

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


def copy_to_clipboard(text: str) -> None:
    """pyperclip でクリップボードへ書く。書けなければ DeliveryError にする。"""
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as error:
        raise DeliveryError(f"クリップボードへ書けませんでした（{error}）") from error
    logger.info(f"クリップボードへ書いた（{len(text)} 文字）")


def send_paste(paste_key: str) -> None:
    """設定の貼り付けのキーを、フォーカスが落ち着くのを待ってから今のアクティブなウィンドウへ送る。"""
    # 1. 貼り付けのキーを、修飾キーと主キーに分ける
    tokens = paste_key.split(KEY_SEPARATOR)
    modifiers = [MODIFIER_KEYS[token] for token in tokens if token in MODIFIER_KEYS]
    main_keys = [token for token in tokens if token not in MODIFIER_KEYS]
    if len(main_keys) != 1:
        raise DeliveryError(f"貼り付けのキーに主キーが 1 つありません（{paste_key}）")

    # 2. 貼り付け先のフォーカスが落ち着くのを待つ
    time.sleep(FOCUS_SETTLE_SEC)

    # 3. 修飾キーを順に押し、主キーを押して離し、修飾キーを逆順に離す
    controller = keyboard.Controller()
    for modifier in modifiers:
        controller.press(modifier)
    controller.press(main_keys[0])
    controller.release(main_keys[0])
    for modifier in reversed(modifiers):
        controller.release(modifier)
    logger.info(f"貼り付けのキーを送った（{paste_key}）")


def send_enter() -> None:
    """Enter を押して離す。待ちは呼ぶ側が置く。"""
    controller = keyboard.Controller()
    controller.press(keyboard.Key.enter)
    controller.release(keyboard.Key.enter)
    logger.info("Enter を送った")
