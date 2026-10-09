"""貼り付けのみ。クリップボードへ書き、貼り付けのキーを送る。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from voice_paste.features.outputs.types import OutputDeps
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


def inject_paste_only(deps: OutputDeps) -> Mapping[str, object]:
    """paste_only に部分適用する copy・paste を返す。"""
    return {"copy": deps.copy, "paste": deps.paste}
