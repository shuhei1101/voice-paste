"""ほかのスレッド（API・ホットキー・ワーカースレッド）からメインスレッドの画面へ知らせを渡す橋渡し。"""

from __future__ import annotations

import logging
from typing import Literal

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

INFO_EVENTS: frozenset[str] = frozenset(
    {"state_changed", "show_recording_window", "output_changed"}
)
"""ログを INFO で出す知らせの種類（それ以外は失敗・断りで WARNING）。"""


class UiBridge(QObject):
    """ほかのスレッドからの知らせを Signal でメインスレッドへ渡す。画面の部品はメインスレッドだけが触る。

    メインスレッドで作り、受け手は `Qt.ConnectionType.QueuedConnection` でつなぐ。
    """

    notified = Signal(str, object)
    """知らせの種類と理由（str | None）。"""

    progressed = Signal(float, float)
    """文字起こしの区間の終わりの時刻と録音の長さ（秒）。"""

    copied = Signal(str)
    """コピーの完了と起こした文字。"""


def notify(
    event: Literal[
        "state_changed",
        "busy",
        "microphone_unavailable",
        "transcription_failed",
        "delivery_failed",
        "api_unavailable",
        "engine_fallback",
        "show_recording_window",
        "output_changed",
    ],
    detail: str | None = None,
    *,
    bridge: UiBridge,
) -> None:
    """UiBridge.notified を emit して、メインスレッドでトレイのアイコン・ダイアログ・画面を変える。"""
    # 状態の変化と録音の画面を戻す指示は INFO、それ以外（失敗・断り）は WARNING
    level = logging.INFO if event in INFO_EVENTS else logging.WARNING
    logger.log(level, f"ユーザーへの知らせ（{event}・{detail}）")
    bridge.notified.emit(event, detail)


def notify_copied(text: str, *, bridge: UiBridge) -> None:
    """UiBridge.copied を emit して、メインスレッドでトレイにコピーの完了の通知を出す。起こした文字はログに書かない。"""
    logger.info("ユーザーへの知らせ（copy_completed）")
    bridge.copied.emit(text)


def report_progress(position_sec: float, duration_sec: float, *, bridge: UiBridge) -> None:
    """UiBridge.progressed を emit して、文字起こし中の表示の進みを変える。"""
    bridge.progressed.emit(position_sec, duration_sec)
