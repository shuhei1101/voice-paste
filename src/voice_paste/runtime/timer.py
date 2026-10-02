"""渡された関数を専用のデーモンスレッドで一定の間隔ごとに呼ぶタイマー。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

THREAD_NAME: str = "repeating-timer"
"""呼び出しのスレッドの名前。"""


class RepeatingTimer:
    """関数を一定の間隔ごとに呼ぶ。呼んだ関数が例外を出してもスレッドを止めない。"""

    def __init__(self, action: Callable[[], object], interval_sec: float) -> None:
        """呼ぶ関数と呼ぶ間隔（秒）を受ける。"""
        self._action = action
        self._interval_sec = interval_sec
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """デーモンスレッドを始め、終わりの合図が立つまで間隔ごとに関数を呼ぶ。"""
        self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """終わりの合図を立て、スレッドの終わりを待つ。"""
        self._stopped.set()
        if self._thread is not None:
            self._thread.join()

    def _loop(self) -> None:
        """間隔だけ待っては関数を呼ぶことを、終わりの合図が立つまで繰り返す。"""
        while not self._stopped.wait(self._interval_sec):
            try:
                self._action()
            except Exception:  # noqa: BLE001 1 回の失敗で定期の呼び出しを止めないため
                logger.exception("定期の呼び出しで想定外の例外")
