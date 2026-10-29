"""貼り付けて送信の設定のモデル。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from voice_paste.shared.settings import RELOAD_IMMEDIATE, OutputSettingsBase, os_default
from voice_paste.shared.types import EnterModifier

ENTER_MODIFIER_LABELS: dict[str, str] = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
"""Enter と一緒に押す修飾キーの値と、設定画面のチェックボックスの名前。"""


class PasteAndSendSettings(OutputSettingsBase):
    """出力先 paste_and_send のオン・オフ・確定のホットキー・貼り付けから送信までの間・Enter と一緒に押す修飾キー。"""

    id: Literal["paste_and_send"] = Field(
        "paste_and_send",
        description="出力先の ID（設定の outputs[] の判別子）",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    hotkey: str = Field(
        os_default("outputs.paste_and_send.hotkey", "<ctrl>+<alt>+d"),
        description="この出力先で確定するホットキー",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    enter_delay_sec: float = Field(
        0.5,
        description="貼り付けてから Enter を送信するまで待つ秒数",
        ge=0,
        json_schema_extra={
            "reload": RELOAD_IMMEDIATE,
            "note": "「貼り付けて送信」と、「ブラウザ添付」の Enter まで送信するプリセットで使う。",
        },
    )
    enter_modifiers: list[EnterModifier] = Field(
        default_factory=list,
        description="Enter と一緒に押す修飾キー。並びと重なりはそのまま持ち、押す順は send_enter が揃える",
        json_schema_extra={
            "reload": RELOAD_IMMEDIATE,
            "choice_labels": ENTER_MODIFIER_LABELS,
        },
    )
