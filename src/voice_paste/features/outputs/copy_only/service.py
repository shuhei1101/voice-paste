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
    notify_copied: Callable[[str], None],
) -> None:
    """起こした文字をクリップボードへ書き、コピーの完了を知らせる。書けなければ DeliveryError のまま伝え、完了は知らせない。"""
    copy(outcome.text)
    notify_copied(outcome.text)


def inject_copy_only(deps: OutputDeps) -> Mapping[str, object]:
    """copy_only に部分適用する copy・notify_copied を返す。"""
    return {"copy": deps.copy, "notify_copied": deps.notify_copied}
