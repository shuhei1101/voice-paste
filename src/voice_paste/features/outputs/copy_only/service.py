"""コピーのみ。クリップボードへ書く。"""

from __future__ import annotations

from collections.abc import Callable

from voice_paste.shared.types import TranscriptionOutcome


def copy_only(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    copy: Callable[[str], None],
) -> None:
    """起こした文字をクリップボードへ書く。書けなければ DeliveryError のまま伝える。"""
    copy(outcome.text)
