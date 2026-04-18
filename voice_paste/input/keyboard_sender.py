"""pynput によるキーボード仮想入力モジュール。"""

import shutil
import subprocess
import time
from pathlib import Path

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


def send_enter(delay: float = 0.05) -> None:
    """Enter キーを仮想入力する。

    :param delay: Enter 送信前の待機秒数
    """
    time.sleep(delay)
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    logger.info("Sent Enter. (delay=%.2fs)", delay)


def _find_msedge() -> str:
    """msedge.exe のパスを返す。見つからなければ 'msedge' を返す。"""
    found = shutil.which("msedge")
    if found:
        return found
    for candidate in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if Path(candidate).exists():
            return candidate
    return "msedge"


def send_to_ai(url: str, delay: float = 2.5) -> None:
    """指定URLのEdge PWAを起動し、クリップボード内容を貼り付けてEnterで送信する。

    :param url: 起動するPWAのURL
    :param delay: 起動後の待機秒数
    """
    msedge = _find_msedge()
    subprocess.Popen([msedge, f"--app={url}", "--new-window"])
    logger.info("Launched Edge app: %s, waiting %.1fs", url, delay)
    time.sleep(delay)
    send_paste()
    send_enter(delay=0.3)
    logger.info("Sent text to AI app: %s", url)
