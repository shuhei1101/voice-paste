"""コピーのみ。クリップボードへ書く。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from voice_paste.features.outputs.types import OutputDeps
from voice_paste.shared.types import TranscriptionOutcome


def copy_only(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    copy: Callable[[str], None],
) -> None:
    """起こした文字をクリップボードへ書く。書けなければ DeliveryError のまま伝える。"""
    copy(outcome.text)


def inject_copy_only(deps: OutputDeps) -> Mapping[str, object]:
    """copy_only に部分適用する copy を返す。"""
    return {"copy": deps.copy}
