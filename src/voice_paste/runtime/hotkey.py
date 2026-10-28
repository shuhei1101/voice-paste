"""グローバルのホットキーの受付（pynput の GlobalHotKeys を別のスレッドで動かす）。"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable

from pynput import keyboard

from voice_paste.shared.errors import HotkeyError

logger = logging.getLogger(__name__)

HOTKEY_STOP_TIMEOUT_SEC: float = 0.5
"""HotkeyListener が止めた受付のスレッドの終わりを待つ上限（秒）。Linux の pynput は次のキー入力まで終わらないため、上限で手放す。値は非機能要件のホットキーの受付の終わりを待つ時間。"""


def _guard(handler: Callable[[], None]) -> Callable[[], None]:
    """pynput のスレッドで例外を出して受付を止めないよう、例外を握ってログに書く関数で包む。"""

    def _guarded() -> None:
        """包んだ関数を呼び、想定外の例外はログに書いて握る。"""
        try:
            handler()
        except Exception:  # noqa: BLE001 pynput のスレッドから漏らすと受付が止まるため
            logger.exception("ホットキーの処理で想定外の例外")

    return _guarded


def validate_hotkeys(hotkeys: Iterable[str]) -> None:
    """ホットキーを pynput が読めるかを、受付を始めずに確かめる。読めなければ HotkeyError を送出する。"""
    for hotkey in hotkeys:
        try:
            keyboard.HotKey.parse(hotkey)
        except ValueError as error:
            raise HotkeyError(f"ホットキーを読めません（{hotkey}）") from error


class HotkeyListener:
    """設定のホットキーを pynput で受け付け、押されたら配線された関数を呼ぶ。セッションは import しない。"""

    def __init__(self) -> None:
        """受付はまだ始めない。"""
        self._listener: keyboard.GlobalHotKeys | None = None
        self._lock = threading.Lock()

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """ホットキーと関数の組を登録して受付を始める。動いていれば、新しい受付を作れたときだけ入れ替える。"""
        with self._lock:
            # 1. 各関数を、例外を握る関数で包む
            guarded = {hotkey: _guard(handler) for hotkey, handler in bindings.items()}

            # 2. 新しい受付を先に作る（作るときに pynput が書式を確かめる。読めなければ動いている受付はそのまま）
            try:
                new_listener = keyboard.GlobalHotKeys(guarded)
            except ValueError as error:
                raise HotkeyError(f"ホットキーを読めません（{error}）") from error

            # 3. 動いている受付があれば止め、スレッドの終わりを上限まで待つ
            self._stop_running()

            # 4. 新しい受付を始める
            new_listener.start()
            self._listener = new_listener
            logger.info(f"ホットキーの受付を始めた（{', '.join(bindings)}）")

    def stop(self) -> None:
        """受付を止め、スレッドの終わりを上限まで待つ。上限を過ぎたら手放して戻る。動いていなければ何もしない。"""
        with self._lock:
            self._stop_running()

    def _stop_running(self) -> None:
        """動いている受付があれば止め、スレッドの終わりを上限まで待って手放す（ロックを取った中で呼ぶ）。"""
        if self._listener is not None:
            self._listener.stop()
            self._listener.join(HOTKEY_STOP_TIMEOUT_SEC)
            # 上限までにスレッドが終わらなかったか
            if self._listener.is_alive():
                # 終わらなかった: 手放して進む（pynput のスレッドは daemon のため、プロセスの終了を妨げない）
                logger.warning(
                    f"ホットキーの受付が {HOTKEY_STOP_TIMEOUT_SEC} 秒たっても終わらないため手放した"
                )
            self._listener = None
