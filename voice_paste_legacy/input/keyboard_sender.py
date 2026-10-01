"""pynput によるキーボード仮想入力モジュール。"""

import time

import pyperclip
from pynput.keyboard import Controller, Key

from voice_paste.exceptions import ClipboardError
from voice_paste.logger import get_logger

logger = get_logger(__name__)

_keyboard = Controller()

# pynput <key> 名 → Key オブジェクト のマッピング
_MOD_MAP: dict[str, Key] = {
    "ctrl": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "win": Key.cmd,
}


def _parse_paste_key(paste_key: str) -> tuple[list[Key], str | Key]:
    """PASTE_KEY 文字列をパースしてモディファイアリストとメインキーに分解する。

    対応フォーマット: `<ctrl>+v` / `<ctrl>+<shift>+v` 等（pynput GlobalHotKeys 形式）
    """
    modifiers: list[Key] = []
    main_key: str | Key = "v"
    for part in paste_key.split("+"):
        name = part.strip("<> ").lower()
        if name in _MOD_MAP:
            modifiers.append(_MOD_MAP[name])
        elif name:
            main_key = name
    return modifiers, main_key


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
    """設定された貼り付けキーを仮想入力する（デフォルト: Ctrl+V）。"""
    from voice_paste import config
    paste_key = config.PASTE_KEY
    modifiers, main_key = _parse_paste_key(paste_key)

    time.sleep(0.1)  # フォーカス安定待ち
    for mod in modifiers:
        _keyboard.press(mod)
    _keyboard.press(main_key)
    _keyboard.release(main_key)
    for mod in reversed(modifiers):
        _keyboard.release(mod)
    logger.info("Sent paste key: %s", paste_key)


def send_enter(delay: float = 0.05) -> None:
    """Enter キーを仮想入力する。

    :param delay: Enter 送信前の待機秒数
    """
    time.sleep(delay)
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    logger.info("Sent Enter. (delay=%.2fs)", delay)
