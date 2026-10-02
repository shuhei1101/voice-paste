"""貼り付けて送信。クリップボードへ書き、貼り付けのキーと、設定の間を置いて Enter を送る。"""

from __future__ import annotations

from collections.abc import Callable

from voice_paste.shared.types import TranscriptionOutcome


def paste_and_send(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    copy: Callable[[str], None],
    paste: Callable[[], None],
    send_enter: Callable[[], None],
    sleep: Callable[[float], None],
    get_enter_delay_sec: Callable[[], float],
) -> None:
    """起こした文字をクリップボードへ書いて貼り付け、設定の間を置いて Enter を送る。"""
    # 1. クリップボードへ書く（書けなければ DeliveryError のまま伝え、キーは送らない）
    copy(outcome.text)

    # 2. 貼り付けのキーを送る
    paste()

    # 3. 設定の間だけ待ち、Enter を送る
    sleep(get_enter_delay_sec())
    send_enter()
