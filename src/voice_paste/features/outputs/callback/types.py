"""返送の中身と、返送先の応答。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class CallbackPayload(BaseModel):
    """呼び出し元へ送る JSON。"""

    session_id: str
    """セッションの ID。"""

    result: Literal["transcribed", "failed", "truncated"]
    """結果の種類。"""

    text: str
    """起こした文字（空もある）。"""

    error: str | None
    """失敗の理由。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class PostResult:
    """post_json が返す、返送先のステータスと再送までに待つ秒数。"""

    status: int
    """返送先が返したステータス。"""

    retry_after_sec: float | None
    """Retry-After を秒に直した値。無い・読めないときは None。"""
