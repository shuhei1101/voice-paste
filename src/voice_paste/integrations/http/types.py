"""JSON の POST の応答と、POST する関数の型。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class PostResult:
    """post_json が返す、送り先のステータスと再送までに待つ秒数。"""

    status: int
    """送り先が返したステータス。"""

    retry_after_sec: float | None
    """Retry-After を秒に直した値。無い・読めないときは None。"""


type PostJsonFn = Callable[[str, dict[str, object], float, Mapping[str, str]], PostResult]
"""送り先・送る JSON・タイムアウト・付けるヘッダーを受け、送り先のステータスと Retry-After を返す。タイムアウト・接続できないことは DeliveryError。"""
