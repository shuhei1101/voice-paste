"""出力先・プリセットの種類の関数型と定義、送る中身。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel

from voice_paste.shared.settings import Preset
from voice_paste.shared.types import TranscriptionOutcome

type OutputFn = Callable[[TranscriptionOutcome, str | None], None]
"""結果と出力先に固有の宛先（返送先の URL。持たない出力先は None）を受け、1 つの出力先へ届ける。届けられなければ DeliveryError。"""

type PresetFn = Callable[[TranscriptionOutcome, Preset], None]
"""結果と確定の操作で選んだプリセット（確定したときの設定の写し）を受け、1 つのプリセットへ届ける。届けられなければ DeliveryError。"""


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


@dataclass(frozen=True, slots=True, kw_only=True)
class PresetKindSpec:
    """カスタムプリセットの種類・表示名・届ける関数の組。"""

    kind: str
    """プリセットの種類。設定の presets[].kind がこの値で指す。"""

    title: str
    """種類の名前（ブラウザ添付・エンドポイントへ送る）。"""

    handler: PresetFn
    """届ける関数。"""


class ResultPayload(BaseModel):
    """呼び出し元へ返す・エンドポイントへ送るが送る JSON。"""

    session_id: str
    """セッションの ID。"""

    result: Literal["transcribed", "failed", "truncated"]
    """結果の種類。"""

    text: str
    """起こした文字（空もある）。"""

    error: str | None
    """失敗の理由。"""

    @classmethod
    def from_outcome(cls, outcome: TranscriptionOutcome) -> Self:
        """結果の session_id・result・text・error を写した中身を作る。"""
        return cls(
            session_id=outcome.session_id,
            result=outcome.result,
            text=outcome.text,
            error=outcome.error,
        )
