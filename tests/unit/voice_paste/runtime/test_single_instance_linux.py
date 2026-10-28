"""runtime/single_instance_linux.py（acquire_single_instance_linux・_peer_uid・LinuxSingleInstanceLock）の単体テスト。

Mock は使わず、実物の flock と抽象名前空間の Unix ドメインソケットで確かめる（名前はテストごとに uuid を付け、
ロックファイルは一時フォルダの instance.lock にする。同じロックを取り合うケースは同じパスを渡す）。
flock は開いたファイルごとに排他が効くため、ほかの持ち主がいる状況も同じスレッドから作れる。
先の持ち主が「頼まれたら放す」ことは、受け手に release を渡して表す。
Linux の flock・fcntl・AF_UNIX を使うため、Windows では流さない。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from voice_paste.shared.errors import StartupError

if TYPE_CHECKING:
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Linux の flock と抽象名前空間のソケットを使うため Windows では流さない",
)

WAIT_SEC = 5.0
"""取れる・頼まれるのを待つ上限。"""

CALLBACK_WAIT_SEC = 1.0
"""受け手が呼ばれる（呼ばれない）のを待つ時間。"""

SHORT_TIMEOUT_SEC = 0.1
"""放されている排他を取るときの待つ上限。"""

NOT_RELEASED_TIMEOUT_SEC = 0.2
"""放されない排他を取るときの待つ上限。"""

SOCKET_DELAY_SEC = 0.3
"""前のプロセスがロックを取ってから終了の依頼のソケットを作るまでの遅れ。"""

SETTLE_SEC = 0.2
"""送信した依頼を、待つスレッドが受けるまでの待ち。"""

CRASH_TIMEOUT_SEC = 1.0
"""片付けずに落ちたプロセスのロックを取るときの待つ上限。"""

HOLDER_WAIT_SEC = 10.0
"""前のプロセスを模すスレッドが、終了の依頼を待つ上限。テストが失敗してもスレッドが残らないようにする。"""

JOIN_TIMEOUT_SEC = 15.0
"""テストが起こしたスレッドの終わりを待つ上限。"""

type AcquireLinuxLock = Callable[[str, float], LinuxSingleInstanceLock]

CHILD_SCRIPT = textwrap.dedent(
    """
    import sys
    import time
    from pathlib import Path

    from voice_paste.runtime.single_instance_linux import acquire_single_instance_linux

    lock = acquire_single_instance_linux(sys.argv[1], 5.0, lock_file=Path(sys.argv[2]))
    print("ready", flush=True)
    time.sleep(60)
    """
)
"""子プロセスで排他を取り、取れたことを知らせてから、終わりの合図を待つスクリプト。"""


def _quit_socket_name(name: str) -> str:
    """排他の名前から、終了の依頼の抽象名前空間のソケットの名前を作る。"""
    return f"\0{name}-quit"


def _send(name: str, payload: bytes) -> None:
    """後から起動したプロセスの代わりに、終了の依頼のソケットへ接続して payload を送信する。"""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(_quit_socket_name(name))
        client.sendall(payload)


class OtherProcessHolder:
    """排他を持つ前のプロセスを模す。ロックを持ち、少し後に終了の依頼のソケットを作って、依頼を待つ。

    前のプロセスが、ロックを取ってからソケットを作るまでの間を再現する。
    終了の依頼（QUIT_REQUEST）を受けたら received を立て、ロックを放して終わる。
    """

    def __init__(self, name: str, lock_file: Path, socket_delay_sec: float) -> None:
        self._name = name
        self._lock_file = lock_file
        self._socket_delay_sec = socket_delay_sec
        self.lock_ready = threading.Event()
        """ロックを持ったら立つ。"""
        self.received = threading.Event()
        """終了の依頼を受けたら立つ（ロックを放す前に立つ）。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """ロックを持ち、遅れてソケットを作り、終了の依頼を受けて放す。"""
        import fcntl

        from voice_paste.runtime.single_instance_linux import QUIT_REQUEST

        lock_fd = os.open(self._lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        self.lock_ready.set()
        # ソケットを作るまでの間（この間は接続が失敗する）
        time.sleep(self._socket_delay_sec)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(_quit_socket_name(self._name))
            server.listen()
            server.settimeout(HOLDER_WAIT_SEC)
            try:
                connection, _ = server.accept()
            except TimeoutError:
                connection = None
            if connection is not None:
                with connection:
                    if connection.recv(len(QUIT_REQUEST)) == QUIT_REQUEST:
                        self.received.set()
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    def finish(self) -> None:
        """スレッドの終わりを待つ。"""
        self._thread.join(JOIN_TIMEOUT_SEC)


@pytest.fixture
def lock_file(tmp_path: Path) -> Path:
    """一時フォルダのロックファイルのパスを返す（ファイルはまだ無い）。"""
    return tmp_path / "instance.lock"


@pytest.fixture
def acquire_linux_lock(lock_file: Path) -> Iterator[AcquireLinuxLock]:
    """テストのスレッドで Linux の排他を取る関数を返す。取ったロックはテストの後に放す。"""
    acquired: list[LinuxSingleInstanceLock] = []

    def _acquire(name: str, timeout_sec: float) -> LinuxSingleInstanceLock:
        """排他を取り、後で放すために控える。"""
        # テストの本体で import し、実装が無いときはそのテストが ImportError で落ちるようにする
        from voice_paste.runtime.single_instance_linux import acquire_single_instance_linux

        lock = acquire_single_instance_linux(name, timeout_sec, lock_file=lock_file)
        acquired.append(lock)
        return lock

    yield _acquire

    for lock in reversed(acquired):
        lock.release()


@pytest.fixture
def other_process_holder(lock_file: Path) -> Iterator[Callable[[str, float], OtherProcessHolder]]:
    """排他を持つ前のプロセスを模すスレッドを始める関数を返す。スレッドはテストの後に終わりを待つ。"""
    started: list[OtherProcessHolder] = []

    def _start(name: str, socket_delay_sec: float) -> OtherProcessHolder:
        """前のプロセスを模すスレッドを始め、後始末のために控える。"""
        holder = OtherProcessHolder(name, lock_file, socket_delay_sec)
        started.append(holder)
        return holder

    yield _start

    for holder in started:
        holder.finish()


@pytest.fixture
def child_process() -> Iterator[Callable[[str, Path], subprocess.Popen[str]]]:
    """子プロセスで排他を取らせる関数を返す。子プロセスはテストの後に必ず終わらせる。"""
    started: list[subprocess.Popen[str]] = []

    def _start(name: str, lock_file: Path) -> subprocess.Popen[str]:
        """子プロセスを起動し、後始末のために控える。"""
        process = subprocess.Popen(
            [sys.executable, "-c", CHILD_SCRIPT, name, str(lock_file)],
            stdout=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(path for path in sys.path if path)},
        )
        started.append(process)
        return process

    yield _start

    for process in started:
        process.kill()
        process.wait(JOIN_TIMEOUT_SEC)
        if process.stdout is not None:
            process.stdout.close()


# === acquire_single_instance_linux ===


def test_acquire_single_instance_linux(unique_name: str, acquire_linux_lock: AcquireLinuxLock) -> None:
    """ほかに持つプロセスが無ければすぐ取れる（正常系）。"""
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

    # 実行
    lock = acquire_linux_lock(unique_name, WAIT_SEC)
    lock.release()
    again = acquire_linux_lock(unique_name, SHORT_TIMEOUT_SEC)

    # 検証
    assert isinstance(lock, LinuxSingleInstanceLock)
    assert isinstance(again, LinuxSingleInstanceLock)


def test_acquire_single_instance_linux_when_held(
    unique_name: str, acquire_linux_lock: AcquireLinuxLock
) -> None:
    """持っている側に終わるよう頼み、放されたら取れる（正常系）。"""
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

    # 準備: 先に取ったロックは、頼まれたら放す
    first = acquire_linux_lock(unique_name, WAIT_SEC)
    on_quit = MagicMock(side_effect=first.release)
    first.on_quit_requested(on_quit)

    # 実行
    later = acquire_linux_lock(unique_name, WAIT_SEC)

    # 検証
    on_quit.assert_called_once()
    assert isinstance(later, LinuxSingleInstanceLock)


def test_acquire_single_instance_linux_when_not_released(
    unique_name: str, acquire_linux_lock: AcquireLinuxLock
) -> None:
    """上限まで放されなければ StartupError になる（異常系）。"""
    # 準備: 先に取ったロックは、頼まれても放さない
    first = acquire_linux_lock(unique_name, WAIT_SEC)
    first.on_quit_requested(MagicMock())

    # 実行・検証: 取れず、もう一度取っても、先のロックが持たれたまま
    with pytest.raises(StartupError):
        acquire_linux_lock(unique_name, NOT_RELEASED_TIMEOUT_SEC)
    with pytest.raises(StartupError):
        acquire_linux_lock(unique_name, NOT_RELEASED_TIMEOUT_SEC)


def test_acquire_single_instance_linux_when_socket_not_ready(
    unique_name: str,
    acquire_linux_lock: AcquireLinuxLock,
    other_process_holder: Callable[[str, float], OtherProcessHolder],
) -> None:
    """前のプロセスのソケットがまだ無くても、接続し直して頼む（正常系）。"""
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

    # 準備: 別のスレッドがロックだけを持ち、少し後に終了の依頼のソケットを作る
    holder = other_process_holder(unique_name, SOCKET_DELAY_SEC)
    lock_ready = holder.lock_ready.wait(WAIT_SEC)

    # 実行
    lock = acquire_linux_lock(unique_name, WAIT_SEC)

    # 検証
    assert lock_ready
    assert isinstance(lock, LinuxSingleInstanceLock)
    assert holder.received.is_set()


def test_acquire_single_instance_linux_when_holder_crashed(
    unique_name: str,
    lock_file: Path,
    acquire_linux_lock: AcquireLinuxLock,
    child_process: Callable[[str, Path], subprocess.Popen[str]],
) -> None:
    """前のプロセスが片付けずに落ちても取れる（正常系）。"""
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

    # 準備: 子プロセスに取らせ、取れたのを見届けてから SIGKILL で終わらせる
    child = child_process(unique_name, lock_file)
    assert child.stdout is not None
    child_ready = child.stdout.readline().strip()
    os.kill(child.pid, signal.SIGKILL)
    child.wait(JOIN_TIMEOUT_SEC)

    # 実行
    lock = acquire_linux_lock(unique_name, CRASH_TIMEOUT_SEC)

    # 検証
    assert child_ready == "ready"
    assert isinstance(lock, LinuxSingleInstanceLock)


# === _peer_uid ===


def test_peer_uid() -> None:
    """自分の接続は自分の uid になる（正常系）。"""
    from voice_paste.runtime.single_instance_linux import _peer_uid

    # 準備
    own, peer = socket.socketpair(socket.AF_UNIX)

    # 実行
    with own, peer:
        uid = _peer_uid(own)

    # 検証
    assert uid == os.getuid()


# === LinuxSingleInstanceLock ===


def test_on_quit_requested_linux(unique_name: str, acquire_linux_lock: AcquireLinuxLock) -> None:
    """頼まれたら受け手を呼ぶ（正常系）。"""
    from voice_paste.runtime.single_instance_linux import QUIT_REQUEST

    # 準備
    called = threading.Event()
    on_quit = MagicMock(side_effect=called.set)
    lock = acquire_linux_lock(unique_name, WAIT_SEC)
    lock.on_quit_requested(on_quit)

    # 実行
    _send(unique_name, QUIT_REQUEST)
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert called_in_time
    on_quit.assert_called_once()


def test_on_quit_requested_linux_when_already_requested(
    unique_name: str, acquire_linux_lock: AcquireLinuxLock
) -> None:
    """受け手を渡す前に頼まれていても取りこぼさない（正常系）。"""
    from voice_paste.runtime.single_instance_linux import QUIT_REQUEST

    # 準備: 受け手を渡す前に頼まれ、待つスレッドがそれを受けるのを待つ
    called = threading.Event()
    on_quit = MagicMock(side_effect=called.set)
    lock = acquire_linux_lock(unique_name, WAIT_SEC)
    _send(unique_name, QUIT_REQUEST)
    time.sleep(SETTLE_SEC)

    # 実行
    lock.on_quit_requested(on_quit)
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert called_in_time
    on_quit.assert_called_once()


def test_on_quit_requested_linux_when_other_message(
    unique_name: str, acquire_linux_lock: AcquireLinuxLock
) -> None:
    """知らない送信では終わらない（正常系）。"""
    from voice_paste.runtime.single_instance_linux import QUIT_REQUEST

    # 準備
    called = threading.Event()
    on_quit = MagicMock(side_effect=called.set)
    lock = acquire_linux_lock(unique_name, WAIT_SEC)
    lock.on_quit_requested(on_quit)

    # 実行: 知らない送信の後に待ち、続けて終了の依頼を送信する
    _send(unique_name, b"hello")
    called_by_other_message = called.wait(SETTLE_SEC)
    _send(unique_name, QUIT_REQUEST)
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert not called_by_other_message
    assert called_in_time
    on_quit.assert_called_once()


def test_on_quit_requested_linux_when_other_user(
    unique_name: str, acquire_linux_lock: AcquireLinuxLock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ほかのユーザーからの依頼では終わらない（正常系）。"""
    import voice_paste.runtime.single_instance_linux as single_instance_linux
    from voice_paste.runtime.single_instance_linux import QUIT_REQUEST

    # 準備: 相手の uid が自分と違う状態にする
    called = threading.Event()
    on_quit = MagicMock(side_effect=called.set)
    lock = acquire_linux_lock(unique_name, WAIT_SEC)
    lock.on_quit_requested(on_quit)
    original_peer_uid = single_instance_linux._peer_uid
    monkeypatch.setattr(single_instance_linux, "_peer_uid", lambda _conn: os.getuid() + 1)

    # 実行: ほかのユーザーの依頼を送信して待ち、相手の uid を自分に戻して、もう一度送信する
    _send(unique_name, QUIT_REQUEST)
    called_by_other_user = called.wait(SETTLE_SEC)
    monkeypatch.setattr(single_instance_linux, "_peer_uid", original_peer_uid)
    _send(unique_name, QUIT_REQUEST)
    called_in_time = called.wait(CALLBACK_WAIT_SEC)

    # 検証
    assert not called_by_other_user
    assert called_in_time
    on_quit.assert_called_once()


def test_release_linux(unique_name: str, acquire_linux_lock: AcquireLinuxLock) -> None:
    """放した後は同じ名前ですぐ取れ、受け手は呼ばれない（正常系）。"""
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

    # 準備
    on_quit = MagicMock()
    lock = acquire_linux_lock(unique_name, WAIT_SEC)
    lock.on_quit_requested(on_quit)

    # 実行
    lock.release()
    lock.release()
    again = acquire_linux_lock(unique_name, SHORT_TIMEOUT_SEC)

    # 検証
    assert isinstance(again, LinuxSingleInstanceLock)
    on_quit.assert_not_called()
