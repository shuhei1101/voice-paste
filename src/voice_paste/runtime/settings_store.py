"""動いている間の今の設定を 1 つ持つ。"""

from __future__ import annotations

import threading

from voice_paste.shared.settings import Settings


class SettingsStore:
    """動いている間の今の設定を 1 つ持ち、設定画面で保存した設定に入れ替える。

    出力先・録音・用語集・画面は設定を値で持たず、使うたびに get で読む。Settings は不変として扱い、入れ替えるだけにする。
    """

    def __init__(self, settings: Settings) -> None:
        """起動時に読んだ設定を受ける。"""
        self._settings = settings
        self._lock = threading.Lock()

    def get(self) -> Settings:
        """今の設定を返す。"""
        with self._lock:
            return self._settings

    def replace(self, settings: Settings) -> None:
        """今の設定を入れ替える。"""
        with self._lock:
            self._settings = settings
