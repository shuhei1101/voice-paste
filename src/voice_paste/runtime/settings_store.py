"""動いている間の今の設定を 1 つ持つ。"""

from __future__ import annotations

import threading

from voice_paste.shared.settings import Settings


class SettingsStore:
    """動いている間の今の設定を 1 つ持ち、設定画面で保存した設定に入れ替える。

    出力先・録音・用語集・画面は設定を値で持たず、使用するたびに get で読み込む。Settings は不変として扱い、入れ替えるだけにする。
    録音セッションが固定（pin）している間は、get は固定した設定を返却し、入れ替えた設定は latest で参照する。
    """

    def __init__(self, settings: Settings) -> None:
        """起動時に読み込んだ設定を受ける。"""
        self._settings = settings
        self._pinned: Settings | None = None
        self._lock = threading.Lock()

    def get(self) -> Settings:
        """録音セッションが使用する設定を返却する（固定していれば固定した設定）。"""
        with self._lock:
            return self._settings if self._pinned is None else self._pinned

    def latest(self) -> Settings:
        """固定によらず、最後に入れ替えた設定を返却する。"""
        with self._lock:
            return self._settings

    def replace(self, settings: Settings) -> None:
        """今の設定を入れ替える（固定している間も、固定した設定は変えない）。"""
        with self._lock:
            self._settings = settings

    def pin(self) -> None:
        """今の設定を固定する。固定していれば何もしない。"""
        with self._lock:
            if self._pinned is None:
                self._pinned = self._settings

    def unpin(self) -> None:
        """固定を解く。"""
        with self._lock:
            self._pinned = None
