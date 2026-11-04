"""Linux（Xorg）の貼り付けのキーの送信。端末アプリなら Ctrl+Shift+V にし、主キーを XTEST で送信する。"""

from __future__ import annotations

import logging
import time

from pynput import keyboard

from voice_paste.integrations.keyboard.active_window_linux import read_active_wm_class
from voice_paste.integrations.keyboard.sender import (
    FOCUS_SETTLE_SEC,
    TERMINAL_WM_CLASSES,
    split_paste_key,
)
from voice_paste.shared.errors import DeliveryError

logger = logging.getLogger(__name__)

TERMINAL_PASTE_MODIFIERS: list[keyboard.Key] = [keyboard.Key.ctrl, keyboard.Key.shift]
"""端末アプリへ貼り付けるときに押す修飾キー（主キーは `v`）。"""

TERMINAL_PASTE_MAIN_KEY: str = "v"
"""端末アプリへ貼り付けるときの主キー。"""


def send_paste_linux(paste_key: str) -> None:
    """端末アプリなら Ctrl+Shift+V、それ以外なら設定の貼り付けのキーを、主キーを XTEST で送信して今のアクティブなウィンドウへ貼り付ける。"""
    # 1. 貼り付けのキーを修飾キーと主キーに分ける（主キーは 1 文字だけ受ける。vk に替えられるのは 1 文字のキーだけのため）
    modifiers, main_key = split_paste_key(paste_key)
    if len(main_key) != 1:
        raise DeliveryError(f"貼り付けのキーの主キーは 1 文字にしてください（{paste_key}）")

    # 2. 貼り付け先のフォーカスが落ち着くのを待つ
    time.sleep(FOCUS_SETTLE_SEC)

    # 3. アクティブなウィンドウが端末アプリか
    wm_class = read_active_wm_class()
    sent_key = paste_key
    if any(name.lower() in TERMINAL_WM_CLASSES for name in wm_class):
        # 端末アプリ: Ctrl+V は貼り付けにならないため Ctrl+Shift+V に替える
        modifiers, main_key = TERMINAL_PASTE_MODIFIERS, TERMINAL_PASTE_MAIN_KEY
        sent_key = "<ctrl>+<shift>+v"
        logger.info(f"端末アプリなので Ctrl+Shift+V を送信する（{', '.join(wm_class)}）")

    # 4. 主キーを vk で渡す（Xorg の pynput では vk が keysym で、ASCII の文字の keysym は文字コードと同じ。文字で渡すと XSendEvent で送られ GTK4 のアプリが受け付けない）
    main_key_code = keyboard.KeyCode.from_vk(ord(main_key))

    # 5. 修飾キーを順に押し、主キーを押して離し、修飾キーを逆順に離す（途中で失敗しても、押した修飾キーは逆順に離す）
    controller = keyboard.Controller()
    pressed: list[keyboard.Key] = []
    try:
        for modifier in modifiers:
            controller.press(modifier)
            pressed.append(modifier)
        controller.press(main_key_code)
        controller.release(main_key_code)
    finally:
        for modifier in reversed(pressed):
            controller.release(modifier)
    logger.info(f"貼り付けのキーを送信した（{sent_key}）")
