"""runtime/timer.py（RepeatingTimer の start・stop）の単体テスト。

呼ぶ関数は、呼ばれた回数を覚える関数に差し替える。間隔は短くして実際に待つ。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from voice_paste.runtime.timer import RepeatingTimer

INTERVAL_SEC = 0.01
WAIT_SEC = 1.0
POLL_SEC = 0.005


class CountingAction:
    """呼ばれた回数を覚える関数。raise_on_first が True なら、1 回目だけ例外を出す。"""

    def __init__(self, *, raise_on_first: bool = False) -> None:
        self.count = 0
        self._raise_on_first = raise_on_first

    def __call__(self) -> None:
        """呼ばれた回数を 1 増やす。"""
        self.count += 1
        if self._raise_on_first and self.count == 1:
            raise RuntimeError("1 回目の失敗")


def _wait_until(condition: Callable[[], bool], timeout_sec: float = WAIT_SEC) -> bool:
    """condition が True になるか timeout_sec が過ぎるまで待ち、True になったかを返す。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(POLL_SEC)
    return condition()


@pytest.fixture
def timers() -> Iterator[list[RepeatingTimer]]:
    """テストで作った RepeatingTimer を、テストの後に止める。"""
    created: list[RepeatingTimer] = []
    yield created
    for timer in created:
        timer.stop()


def test_start(timers: list[RepeatingTimer]) -> None:
    """間隔ごとに呼ぶ（正常系）。"""
    from voice_paste.runtime.timer import RepeatingTimer

    # 準備
    action = CountingAction()
    timer = RepeatingTimer(action, INTERVAL_SEC)
    timers.append(timer)

    # 実行
    timer.start()

    # 検証
    assert _wait_until(lambda: action.count >= 3)


def test_start_when_action_raised(
    timers: list[RepeatingTimer], caplog: pytest.LogCaptureFixture
) -> None:
    """例外でも止まらない（正常系）。"""
    from voice_paste.runtime.timer import RepeatingTimer

    # 準備
    caplog.set_level(logging.ERROR)
    action = CountingAction(raise_on_first=True)
    timer = RepeatingTimer(action, INTERVAL_SEC)
    timers.append(timer)

    # 実行
    timer.start()

    # 検証
    assert _wait_until(lambda: action.count >= 3)
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1


def test_stop(timers: list[RepeatingTimer]) -> None:
    """止めた後は呼ばない（正常系）。"""
    from voice_paste.runtime.timer import RepeatingTimer

    # 準備
    action = CountingAction()
    timer = RepeatingTimer(action, INTERVAL_SEC)
    timers.append(timer)
    timer.start()
    assert _wait_until(lambda: action.count >= 1)

    # 実行
    timer.stop()
    count_after_stop = action.count
    time.sleep(INTERVAL_SEC * 5)

    # 検証
    assert action.count == count_after_stop
    assert not timer._thread.is_alive()
