"""貼り付けて送信の設定のモデル。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from voice_paste.shared.settings import RELOAD_IMMEDIATE, OutputSettingsBase


class PasteAndSendSettings(OutputSettingsBase):
    """出力先 paste_and_send のオン・オフ・確定のホットキー・貼り付けから送信までの間。"""

    id: Literal["paste_and_send"] = Field(
        "paste_and_send",
        description="出力先の ID（設定の outputs[] の判別子）",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    hotkey: str = Field(
        "<ctrl>+<alt>+d",
        description="この出力先で確定するホットキー",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    enter_delay_sec: float = Field(
        0.5,
        description="貼り付けてから Enter を送るまで待つ秒数",
        ge=0,
        json_schema_extra={
            "reload": RELOAD_IMMEDIATE,
            "note": "「貼り付けて送信」と、「ブラウザ添付」の Enter まで送るプリセットで使う。",
        },
    )
