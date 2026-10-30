"""貼り付けのみの設定のモデル。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from voice_paste.shared.settings import RELOAD_IMMEDIATE, OutputSettingsBase, os_default


class PasteOnlySettings(OutputSettingsBase):
    """出力先 paste_only のオン・オフ・確定のホットキー。"""

    id: Literal["paste_only"] = Field(
        "paste_only",
        description="出力先の ID（設定の outputs[] の判別子）",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    hotkey: str = Field(
        os_default("outputs.paste_only.hotkey", "<ctrl>+<alt>+v"),
        description="この出力先で確定するホットキー",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
