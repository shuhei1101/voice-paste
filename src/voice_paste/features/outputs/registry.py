"""出力先の一覧。出力先を足すときに既存のモジュールで変えるのはここだけ。"""

from __future__ import annotations

from voice_paste.features.outputs.callback import deliver_to_caller
from voice_paste.features.outputs.types import OutputSpec

CALLBACK_OUTPUT_ID: str = "callback"
"""呼び出し元へ返す出力先の ID。"""

OUTPUTS: tuple[OutputSpec, ...] = (
    OutputSpec(
        id=CALLBACK_OUTPUT_ID,
        title="呼び出し元へ返す",
        handler=deliver_to_caller,  # type: ignore[arg-type] 再送の関数などは main.py が部分適用する
        api_only=True,
    ),
)
"""登録した出力先。ほかの出力先は #20 が足す。"""
