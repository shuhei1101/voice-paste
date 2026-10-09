"""runtime/single_instance.py（instance_name・acquire_single_instance・SingleInstanceLock）の単体テスト。

Mock は使わず、実物の Win32 の名前付きのミューテックスとイベントで確かめる（名前はテストごとに uuid を付ける）。
名前付きのミューテックスは取ったスレッドだけが放せ、同じスレッドからは何度でも取れてしまうため、
ほかの持ち主がいる状況と放した後の取り直しは、別のスレッドで取って確かめる（background_acquire）。
先の持ち主が「頼まれたら放す」ことは、受け手が知らせるだけにして、取ったテストのスレッドが放して表す。
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from tests.unit.voice_paste.runtime.helpers import (
    BackgroundAcquire,
    OtherProcessHolder,
    request_quit,
    set_event,
)
from voice_paste.shared.errors import StartupError

if TYPE_CHECKING:
    from voice_paste.runtime.single_instance import SingleInstanceLock

WAIT_SEC = 5.0
"""別のスレッドで取れる・頼まれるのを待つ上限。"""

CALLBACK_WAIT_SEC = 1.0
"""受け手が呼ばれる（呼ばれない）のを待つ時間。"""

SHORT_TIMEOUT_SEC = 0.1
"""放されている排他を取るときの待つ上限。"""

NOT_RELEASED_TIMEOUT_SEC = 0.2
"""放されない排他を取るときの待つ上限。"""

EVENT_DELAY_SEC = 0.3
"""前のプロセスがミューテックスを作ってからイベントを作るまでの遅れ。"""

SETTLE_SEC = 0.2
"""立てた依頼を、待つスレッドが受けるまでの待ち。"""

type AcquireLock = Callable[[str, float], SingleInstanceLock]
type BackgroundAcquireFactory = Callable[[str, float], BackgroundAcquire]


# === instance_name ===


def test_instance_name() -> None:
    """同じフォルダは大文字・小文字によらず同じ名前になる（正常系）。"""
    from voice_paste.runtime.single_instance import instance_name

    # 実行
    name = instance_name(Path("C:/Users/a/AppData/Roaming/voice-paste"))
    name_of_other_case = instance_name(Path("c:/users/a/appdata/roaming/VOICE-PASTE"))

    # 検証
    assert name == name_of_other_case
    assert re.fullmatch(r"voice-paste-[0-9a-f]{16}", name)


def test_instance_name_when_other_folder(tmp_path: Path) -> None:
    """違うフォルダは違う名前になる（正常系）。"""
    from voice_paste.runtime.single_instance import instance_name

    # 実行
    default_name = instance_name(Path("C:/Users/a/AppData/Roaming/voice-paste"))
    temporary_name = instance_name(tmp_path)

    # 検証
    assert default_name != temporary_name


# === acquire_single_instance ===


def test_acquire_single_instance(
    unique_name: str,
    acquire_lock: AcquireLock,
    background_acquire: BackgroundAcquireFactory,
) -> None:
    """ほかに持つプロセスが無ければすぐ取れる（正常系）。"""
    from voice_paste.runtime.single_instance import SingleInstanceLock

    # 実行
    lock = acquire_lock(unique_name, WAIT_SEC)
    lock.release()
    again = background_acquire(unique_name, SHORT_TIMEOUT_SEC)
    again_decided = again.wait(WAIT_SEC)

    # 検証
    assert isinstance(lock, SingleInstanceLock)
    assert again_decided
    assert isinstance(again.lock, SingleInstanceLock)


def test_acquire_single_instance_when_held(
    unique_name: str,
    acquire_lock: AcquireLock,
    background_acquire: BackgroundAcquireFactory,
) -> None:
    """持っている側に終わるよう頼み、放されたら取れる（正常系）。"""
    from voice_paste.runtime.single_instance import SingleInstanceLock

    # 準備: 先に取ったロックは、頼まれたら知らせる（放すのは取ったテストのスレッド）
    requested = threading.Event()
    on_quit = MagicMock(side_effect=lambda: requested.set())
    first = acquire_lock(unique_name, WAIT_SEC)
    first.on_quit_requested(on_quit)

    # 実行: 別のスレッドで取り始め、頼まれたのを見届けて放す
    later = background_acquire(unique_name, WAIT_SEC)
    requested_in_time = requested.wait(WAIT_SEC)
    first.release()
    later_decided = later.wait(WAIT_SEC)

    # 検証
    assert requested_in_time
    on_quit.assert_called_once()
    assert later_decided
    assert later.error is None
    assert isinstance(later.lock, SingleInstanceLock)


def test_acquire_single_instance_when_not_released(
    unique_name: str,
    acquire_lock: AcquireLock,
    background_acquire: BackgroundAcquireFactory,
) -> None:
    """上限まで放されなければ StartupError になる（異常系）。"""
    # 準備: 先に取ったロックは、頼まれても放さない
    first = acquire_lock(unique_name, WAIT_SEC)
    first.on_quit_requested(MagicMock())

    # 実行: 別のスレッドで取り、続けて別のスレッドでもう一度取って、先のロックが持たれたままかを確かめる
    later = background_acquire(unique_name, NOT_RELEASED_TIMEOUT_SEC)
    later_decided = later.wait(WAIT_SEC)
    retry = background_acquire(unique_name, NOT_RELEASED_TIMEOUT_SEC)
    retry_decided = retry.wait(WAIT_SEC)

    # 検証
    assert later_decided
    assert isinstance(later.error, StartupError)
    assert retry_decided
    assert isinstance(retry.error, StartupError)


def test_acquire_single_instance_when_taken_over(
    unique_name: str,
    acquire_lock: AcquireLock,
    background_acquire: BackgroundAcquireFactory,
    open_quit_event: Callable[[str], int],
) -> None:
    """前の持ち主が依頼を受けて放した直後に取ったロックは、受け手を呼ばない（正常系）。"""
    # 準備: 先に取ったロックは、頼まれたら知らせる
    requested = threading.Event()
    first = acquire_lock(unique_name, WAIT_SEC)
    first.on_quit_requested(requested.set)
    later = background_acquire(unique_name, WAIT_SEC)

    # 実行: 頼まれたのを見届け、同じ名前のイベントのハンドルを開いたまま、3 つ目の依頼として立ててから放す
    requested_in_time = requested.wait(WAIT_SEC)
    set_event(open_quit_event(unique_name))
    first.release()
    later_decided = later.wait(WAIT_SEC)
    assert later.lock is not None
    # 後から取ったロックに受け手を渡し、立ったまま残っていた依頼で呼ばれないことを確かめる
    later_requested = threading.Event()
    later.lock.on_quit_requested(later_requested.set)
    later_called = later_requested.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert requested_in_time
    assert later_decided
    assert not later_called


def test_acquire_single_instance_when_event_not_ready(
    unique_name: str,
    acquire_lock: AcquireLock,
    other_process_holder: Callable[[str, float], OtherProcessHolder],
) -> None:
    """前のプロセスのイベントがまだ無くても、開き直して頼む（正常系）。"""
    from voice_paste.runtime.single_instance import SingleInstanceLock

    # 準備: 別のスレッドがミューテックスだけを持ち、少し後に終了の依頼のイベントを作る
    holder = other_process_holder(unique_name, EVENT_DELAY_SEC)
    mutex_ready = holder.mutex_ready.wait(WAIT_SEC)

    # 実行
    lock = acquire_lock(unique_name, WAIT_SEC)

    # 検証
    assert mutex_ready
    assert isinstance(lock, SingleInstanceLock)
    assert holder.received.is_set()


# === SingleInstanceLock ===


def test_on_quit_requested(unique_name: str, acquire_lock: AcquireLock) -> None:
    """頼まれたら受け手を呼ぶ（正常系）。"""
    # 準備
    called = threading.Event()
    on_quit = MagicMock(side_effect=lambda: called.set())
    lock = acquire_lock(unique_name, WAIT_SEC)
    lock.on_quit_requested(on_quit)

    # 実行
    request_quit(unique_name)
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert called_in_time
    on_quit.assert_called_once()


def test_on_quit_requested_when_already_requested(
    unique_name: str, acquire_lock: AcquireLock
) -> None:
    """受け手を渡す前に頼まれていても取りこぼさない（正常系）。"""
    # 準備: 受け手を渡す前に頼まれ、待つスレッドがそれを受けるのを待つ
    called = threading.Event()
    on_quit = MagicMock(side_effect=lambda: called.set())
    lock = acquire_lock(unique_name, WAIT_SEC)
    request_quit(unique_name)
    time.sleep(SETTLE_SEC)

    # 実行
    lock.on_quit_requested(on_quit)
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert called_in_time
    on_quit.assert_called_once()


def test_release(
    unique_name: str,
    acquire_lock: AcquireLock,
    background_acquire: BackgroundAcquireFactory,
) -> None:
    """放した後は同じ名前ですぐ取れ、受け手は呼ばれない（正常系）。"""
    from voice_paste.runtime.single_instance import SingleInstanceLock

    # 準備
    on_quit = MagicMock()
    lock = acquire_lock(unique_name, WAIT_SEC)
    lock.on_quit_requested(on_quit)

    # 実行
    lock.release()
    lock.release()
    again = background_acquire(unique_name, SHORT_TIMEOUT_SEC)
    again_decided = again.wait(WAIT_SEC)

    # 検証
    assert again_decided
    assert again.error is None
    assert isinstance(again.lock, SingleInstanceLock)
    on_quit.assert_not_called()
