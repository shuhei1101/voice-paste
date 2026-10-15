"""features/outputs の単体テスト用の偽物と組み立て。

出力先の配線に渡すもの（OutputDeps）の関数は全て Mock にする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from voice_paste.features.outputs.types import OutputDeps


def make_output_deps(**overrides: Any) -> OutputDeps:
    """全ての関数を Mock にした OutputDeps を作る。overrides は項目ごとの差し替え。"""
    from voice_paste.features.outputs.types import OutputDeps as OutputDepsModel
    from voice_paste.shared.settings import Settings

    fields: dict[str, Any] = {
        "copy": MagicMock(),
        "paste": MagicMock(),
        "send_enter": MagicMock(),
        "sleep": MagicMock(),
        "jitter": MagicMock(),
        "post": MagicMock(),
        "get_settings": MagicMock(return_value=Settings()),
        "notify_copied": MagicMock(),
    }
    fields.update(overrides)
    return OutputDepsModel(**fields)
