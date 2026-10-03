"""新しい構成の単体テスト（voice_paste）の共通フィクスチャ。

単一インスタンスの排他（実物の Win32 の名前付きのミューテックスとイベント）を使うテストが、
名前・取ったロック・開いたハンドルを後始末つきで扱えるようにする。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.unit.voice_paste.runtime.helpers import BackgroundAcquire, OtherProcessHolder
    from voice_paste.runtime.single_instance import SingleInstanceLock


@pytest.fixture
def unique_name() -> str:
    """テストごとに重ならない排他の名前を返す。"""
    return f"voice-paste-test-{uuid.uuid4().hex}"


@pytest.fixture
def acquire_lock() -> Iterator[Callable[[str, float], SingleInstanceLock]]:
    """テストのスレッドで排他を取る関数を返す。取ったロックはテストの後に放す。"""
    acquired: list[SingleInstanceLock] = []

    def _acquire(name: str, timeout_sec: float) -> SingleInstanceLock:
        """排他を取り、後で放すために控える。"""
        # テストの本体で import し、実装が無いときはそのテストが ImportError で落ちるようにする
        from voice_paste.runtime.single_instance import acquire_single_instance

        lock = acquire_single_instance(name, timeout_sec)
        acquired.append(lock)
        return lock

    yield _acquire

    for lock in reversed(acquired):
        lock.release()


@pytest.fixture
def background_acquire() -> Iterator[Callable[[str, float], BackgroundAcquire]]:
    """別のスレッドで排他を取り始める関数を返す。取れたロックはテストの後にそのスレッドで放す。"""
    from tests.unit.voice_paste.runtime.helpers import BackgroundAcquire

    started: list[BackgroundAcquire] = []

    def _start(name: str, timeout_sec: float) -> BackgroundAcquire:
        """別のスレッドで取り始め、後始末のために控える。"""
        holder = BackgroundAcquire(name, timeout_sec)
        started.append(holder)
        return holder

    yield _start

    for holder in reversed(started):
        holder.finish()


@pytest.fixture
def open_quit_event() -> Iterator[Callable[[str], int]]:
    """終了の依頼のイベントを開く関数を返す。開いたハンドルはテストの後に閉じる。"""
    from tests.unit.voice_paste.runtime import helpers

    opened: list[int] = []

    def _open(name: str) -> int:
        """イベントを開き、後で閉じるために控える。"""
        handle = helpers.open_quit_event(name)
        opened.append(handle)
        return handle

    yield _open

    for handle in opened:
        helpers.close_handle(handle)


@pytest.fixture
def other_process_holder() -> Iterator[Callable[[str, float], OtherProcessHolder]]:
    """排他を持つ前のプロセスを模すスレッドを始める関数を返す。スレッドはテストの後に終わりを待つ。"""
    from tests.unit.voice_paste.runtime.helpers import OtherProcessHolder

    started: list[OtherProcessHolder] = []

    def _start(name: str, event_delay_sec: float) -> OtherProcessHolder:
        """前のプロセスを模すスレッドを始め、後始末のために控える。"""
        holder = OtherProcessHolder(name, event_delay_sec)
        started.append(holder)
        return holder

    yield _start

    for holder in started:
        holder.finish()
