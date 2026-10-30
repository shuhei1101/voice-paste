"""runtime/send_hotkey.py（main）の単体テスト。

Mock は使わず、実物の flock と抽象名前空間の Unix ドメインソケットで確かめる（名前はテストごとに uuid を付け、
ロックファイルは一時フォルダの instance.lock にする）。
Linux の AF_UNIX を使うため、Windows では流さない。
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Linux の抽象名前空間のソケットを使うため Windows では流さない",
)

WAIT_SEC = 5.0
"""排他を取る上限。"""

CALLBACK_WAIT_SEC = 1.0
"""受け手が呼ばれるのを待つ時間。"""


@pytest.fixture
def acquire_linux_lock(tmp_path: Path) -> Iterator[Callable[[str], LinuxSingleInstanceLock]]:
    """テストのスレッドで Linux の排他を取る関数を返す。取ったロックはテストの後に放す。"""
    acquired: list[LinuxSingleInstanceLock] = []

    def _acquire(name: str) -> LinuxSingleInstanceLock:
        """排他を取り、後で放すために控える。"""
        # テストの本体で import し、実装が無いときはそのテストが ImportError で落ちるようにする
        from voice_paste.runtime.single_instance_linux import acquire_single_instance_linux

        lock = acquire_single_instance_linux(name, WAIT_SEC, lock_file=tmp_path / "instance.lock")
        acquired.append(lock)
        return lock

    yield _acquire

    for lock in reversed(acquired):
        lock.release()


def test_main(unique_name: str, acquire_linux_lock: Callable[[str], LinuxSingleInstanceLock]) -> None:
    """常駐サービスへホットキーを送信する（正常系）。"""
    from voice_paste.runtime.send_hotkey import main

    # 準備: 一意の名前で排他を取り、ホットキーの受け手を渡す
    called = threading.Event()
    on_hotkey = MagicMock(side_effect=lambda _hotkey: called.set())
    lock = acquire_linux_lock(unique_name)
    lock.on_hotkey(on_hotkey)

    # 実行
    exit_code = main([unique_name, "<cmd>+<alt>+d"])
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert exit_code == 0
    assert called_in_time
    on_hotkey.assert_called_once_with("<cmd>+<alt>+d")


def test_main_when_not_running(unique_name: str) -> None:
    """常駐サービスが動いていなければ何もしない（正常系）。"""
    from voice_paste.runtime.send_hotkey import main

    # 実行: 誰も待っていない名前へ送信する
    exit_code = main([unique_name, "<cmd>+<alt>+d"])

    # 検証
    assert exit_code == 0


def test_main_when_wrong_args(unique_name: str) -> None:
    """引数の数が違えば 2 を返す（異常系）。"""
    from voice_paste.runtime.send_hotkey import main

    # 実行
    exit_code = main([unique_name])

    # 検証
    assert exit_code == 2
