"""AI チャットへ送る。選んだ送り先の画面をアプリのウィンドウで開き、貼り付けて送る。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome

logger = logging.getLogger(__name__)


def send_to_ai_chat(
    outcome: TranscriptionOutcome,
    target: str | None,
    *,
    copy: Callable[[str], None],
    open_window: Callable[[str], None],
    paste: Callable[[], None],
    send_enter: Callable[[], None],
    sleep: Callable[[float], None],
    get_open_delay_sec: Callable[[], float],
    get_enter_delay_sec: Callable[[], float],
) -> None:
    """起こした文字をクリップボードへ書き、送り先の画面を開いて、設定の間を置いて貼り付けて送る。"""
    # 1. 送り先を選ばずに確定したなら、何もせずに断る
    if target is None:
        raise DeliveryError("AI チャットの送り先が選ばれていません")

    # 2. クリップボードへ書き、送り先をアプリのウィンドウで開く（失敗は DeliveryError のまま伝え、そこで止める）
    copy(outcome.text)
    open_window(target)

    # 3. 画面が開くまで待ち、貼り付けのキーを送る
    sleep(get_open_delay_sec())
    paste()

    # 4. 貼り付けてから Enter を送るまで待ち、Enter を送る
    sleep(get_enter_delay_sec())
    send_enter()
    logger.info(f"AI チャットへ送った（{outcome.session_id}・送り先: {target}）")
