"""ui/bridge.py（UiBridge・notify・notify_copied・report_progress）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Qt, Slot

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

WAIT_SEC = 2.0
POLL_SEC = 0.01


class Receiver(QObject):
    """UiBridge の Signal を受け、受けた値と受けたスレッドを覚える（メインスレッドの受け手の代わり）。"""

    def __init__(self) -> None:
        super().__init__()
        self.received: list[tuple[Any, ...]] = []
        self.threads: list[threading.Thread] = []

    @Slot(str, object)
    def on_notified(self, event: str, detail: object) -> None:
        """知らせを受けた値とスレッドを覚える。"""
        self.received.append((event, detail))
        self.threads.append(threading.current_thread())

    @Slot(float, float)
    def on_progressed(self, position_sec: float, duration_sec: float) -> None:
        """進みを受けた値を覚える。"""
        self.received.append((position_sec, duration_sec))
        self.threads.append(threading.current_thread())

    @Slot(str)
    def on_copied(self, text: str) -> None:
        """コピーの完了で渡された起こした文字を覚える。"""
        self.received.append((text,))
        self.threads.append(threading.current_thread())


def _process_events_until(condition: Any) -> bool:
    """condition が True になるか WAIT_SEC が過ぎるまで、イベントループを回して待つ。"""
    deadline = time.monotonic() + WAIT_SEC
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(POLL_SEC)
    return bool(condition())


# === notify ===


def test_notify(qapp: QApplication, caplog: pytest.LogCaptureFixture) -> None:
    """知らせを Signal で渡す（正常系）。"""
    from voice_paste.ui.bridge import UiBridge, notify

    # 準備
    caplog.set_level(logging.INFO)
    bridge = UiBridge()
    receiver = Receiver()
    bridge.notified.connect(receiver.on_notified, Qt.ConnectionType.QueuedConnection)

    # 実行
    notify("delivery_failed", "クリップボードに書けない", bridge=bridge)
    _process_events_until(lambda: receiver.received)

    # 検証
    assert receiver.received == [("delivery_failed", "クリップボードに書けない")]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_notify_from_other_thread(qapp: QApplication) -> None:
    """ほかのスレッドからの知らせをメインスレッドで受ける（正常系）。"""
    from voice_paste.ui.bridge import UiBridge, notify

    # 準備
    bridge = UiBridge()
    receiver = Receiver()
    bridge.notified.connect(receiver.on_notified, Qt.ConnectionType.QueuedConnection)
    sender = threading.Thread(target=lambda: notify("state_changed", None, bridge=bridge))

    # 実行
    sender.start()
    sender.join()
    _process_events_until(lambda: receiver.received)

    # 検証
    assert receiver.received == [("state_changed", None)]
    assert receiver.threads == [threading.main_thread()]


# === notify_copied ===


def test_notify_copied(qapp: QApplication, caplog: pytest.LogCaptureFixture) -> None:
    """起こした文字を Signal で渡し、ログには書かない（正常系）。"""
    from voice_paste.ui.bridge import UiBridge, notify_copied

    # 準備
    caplog.set_level(logging.INFO)
    bridge = UiBridge()
    receiver = Receiver()
    bridge.copied.connect(receiver.on_copied, Qt.ConnectionType.QueuedConnection)

    # 実行
    notify_copied("テストの文字", bridge=bridge)
    _process_events_until(lambda: receiver.received)

    # 検証
    assert receiver.received == [("テストの文字",)]
    infos = [record for record in caplog.records if record.levelno == logging.INFO]
    assert len(infos) == 1
    assert all("テストの文字" not in record.getMessage() for record in caplog.records)


# === report_progress ===


def test_report_progress(qapp: QApplication) -> None:
    """進みを Signal で渡す（正常系）。"""
    from voice_paste.ui.bridge import UiBridge, report_progress

    # 準備
    bridge = UiBridge()
    receiver = Receiver()
    bridge.progressed.connect(receiver.on_progressed, Qt.ConnectionType.QueuedConnection)

    # 実行
    report_progress(3.1, 5.0, bridge=bridge)
    _process_events_until(lambda: receiver.received)

    # 検証
    assert receiver.received == [(3.1, 5.0)]
