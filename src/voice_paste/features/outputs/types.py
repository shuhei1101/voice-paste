"""出力先の関数型と、出力先の定義。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from voice_paste.shared.types import TranscriptionOutcome

type OutputFn = Callable[[TranscriptionOutcome, str | None], None]
"""結果と出力先に固有の宛先（AI チャットの送り先の URL・返送先の URL。持たない出力先は None）を受け、1 つの出力先へ届ける。届けられなければ DeliveryError。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputSpec:
    """出力先の ID・表示名・届ける関数の組。"""

    id: str
    """出力先の ID。設定の出力先の一覧と確定の操作がこの ID で指す。"""

    title: str
    """画面に出す名前。"""

    handler: OutputFn
    """届ける関数。"""

    api_only: bool = False
    """API から始めた録音だけが使うか（呼び出し元へ返すだけが True）。"""
