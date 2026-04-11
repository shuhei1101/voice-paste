"""pynput によるキーボード仮想入力モジュール。"""

import time

import pyperclip
from pynput.keyboard import Controller, Key

from voice_paste.exceptions import ClipboardError
from voice_paste.logger import get_logger

logger = get_logger(__name__)

_keyboard = Controller()


def copy_to_clipboard(text: str) -> None:
    """
    テキストをクリップボードにコピーする。

    :param text: コピーするテキスト
    :raises ClipboardError: クリップボード操作に失敗した場合
    """
    try:
        pyperclip.copy(text)
        logger.info("Text copied to clipboard: %d chars", len(text))
    except Exception as e:
        raise ClipboardError(f"Failed to copy to clipboard: {e}") from e


def send_paste() -> None:
    """Ctrl+V を仮想入力する。"""
    time.sleep(0.1)  # フォーカス安定待ち
    with _keyboard.pressed(Key.ctrl):
        _keyboard.press("v")
        _keyboard.release("v")
    logger.info("Sent Ctrl+V.")


def send_enter() -> None:
    """Enter キーを仮想入力する。"""
    time.sleep(0.05)
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    logger.info("Sent Enter.")
