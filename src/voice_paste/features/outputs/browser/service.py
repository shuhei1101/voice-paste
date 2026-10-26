"""ブラウザ添付。選んだプリセットの画面をアプリのウィンドウで開き、貼り付けて、設定によって Enter まで送信する。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.settings import BrowserPreset, Preset
from voice_paste.shared.types import TranscriptionOutcome

logger = logging.getLogger(__name__)


def send_to_browser(
    outcome: TranscriptionOutcome,
    preset: Preset,
    *,
    copy: Callable[[str], None],
    open_window: Callable[[str], None],
    paste: Callable[[], None],
    send_enter: Callable[[], None],
    sleep: Callable[[float], None],
    get_open_delay_sec: Callable[[], float],
    get_enter_delay_sec: Callable[[], float],
) -> None:
    """起こした文字をクリップボードへ書き、プリセットの画面を開いて、設定の間を置いて貼り付け、Enter まで送信するなら Enter を送信する。"""
    # 1. ブラウザ添付のプリセットでなければ断る（種類と関数の取り違え）
    if not isinstance(preset, BrowserPreset):
        raise DeliveryError(f"ブラウザ添付のプリセットではありません（種類: {preset.kind}）")

    # 2. クリップボードへ書き、プリセットの URL をアプリのウィンドウで開く（失敗は DeliveryError のまま伝え、そこで止める）
    copy(outcome.text)
    open_window(preset.url)

    # 3. 画面が開くまで待ち、貼り付けのキーを送信する
    sleep(get_open_delay_sec())
    paste()

    # 4. Enter まで送信するプリセットだけ、貼り付けてから待って Enter を送信する（送信しないなら貼り付けで止める）
    if preset.send_enter:
        sleep(get_enter_delay_sec())
        send_enter()
    logger.info(
        f"ブラウザ添付で届けた（{outcome.session_id}・{preset.title}・Enter まで送信した: {preset.send_enter}）"
    )
