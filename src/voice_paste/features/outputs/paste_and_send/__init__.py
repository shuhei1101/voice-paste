"""出力先 paste_and_send（貼り付けて送信）。"""

from voice_paste.features.outputs.paste_and_send.service import (
    inject_paste_and_send,
    paste_and_send,
    read_enter_delay_sec,
)
from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings

__all__ = [
    "PasteAndSendSettings",
    "inject_paste_and_send",
    "paste_and_send",
    "read_enter_delay_sec",
]
