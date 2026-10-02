"""貼り付けのみ。クリップボードへ書き、貼り付けのキーを送る。"""

from __future__ import annotations

from collections.abc import Callable

from voice_paste.shared.types import TranscriptionOutcome


def paste_only(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    copy: Callable[[str], None],
    paste: Callable[[], None],
) -> None:
    """起こした文字をクリップボードへ書いて貼り付ける。"""
    # 1. クリップボードへ書く（書けなければ DeliveryError のまま伝え、キーは送らない）
    copy(outcome.text)

    # 2. 貼り付けのキーを送る
    paste()
