"""Linux の単一インスタンスの排他。ロックファイルを flock で取り、後から起動したプロセスが前のプロセスへ終わるよう頼む。

ロックファイル（AppPaths.lock_file）を持つプロセスが、常駐サービスの 1 つだけ。
後から起動したプロセスは、終了の依頼のソケット（抽象名前空間の `\\0{名前}-quit`）へ QUIT_REQUEST を送信して前のプロセスに終わるよう頼み、
ロックが放されるのを待ってから取る。プロセスの番号での強制終了はしない（番号を使い回された無関係なプロセスを止めない）。
プロセスが片付けずに落ちても、OS がロックとソケットを放すため、次の起動はそのまま取れる。
"""

from __future__ import annotations

import fcntl
import logging
import os
import select
import socket
import struct
import threading
import time
from collections.abc import Callable
from pathlib import Path

from voice_paste.shared.errors import StartupError

logger = logging.getLogger(__name__)

LOCK_RETRY_INTERVAL_SEC: float = 0.1
"""前のプロセスに終わるよう頼んだ後、flock を取り直し・接続し直す間隔。取れるまでの遅れを 0.1 秒までに抑える。"""

QUIT_REQUEST: bytes = b"quit"
"""後から起動したプロセスが終了の依頼のソケットへ送信するバイト列。"""

HOTKEY_REQUEST_PREFIX: bytes = b"hotkey:"
"""send_hotkey が終了の依頼のソケットへ、押されたホットキーの前に付けて送信するバイト列。"""

MAX_REQUEST_BYTES: int = 256
"""終了の依頼のソケットで 1 つの接続から読むバイト数の上限（`hotkey:` と設定のホットキーが収まる長さ）。"""

LOCK_FILE_MODE: int = 0o600
"""ロックファイルを作るときの権限。"""

CONNECTION_READ_TIMEOUT_SEC: float = 1.0
"""終了の依頼のソケットで、接続を受けてから送信されるのを待つ上限。送信しない接続で待つスレッドを止めない。"""

PEER_CREDENTIALS_FORMAT: str = "3i"
"""SO_PEERCRED で読む struct ucred（pid・uid・gid の 3 つの int）の形式。"""

PEER_UID_INDEX: int = 1
"""struct ucred の uid の位置。"""

STOP_SIGNAL: bytes = b"x"
"""待つスレッドを止める合図として停止のソケットへ送信するバイト列。"""


def _quit_socket_name(name: str) -> str:
    """排他の名前から、終了の依頼のソケットの抽象名前空間の名前（先頭が NUL）を作る。"""
    return f"\0{name}-quit"


def _peer_uid(conn: socket.socket) -> int:
    """Unix ドメインソケットの接続の相手の uid を SO_PEERCRED で読む。"""
    credentials = conn.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize(PEER_CREDENTIALS_FORMAT)
    )
    return struct.unpack(PEER_CREDENTIALS_FORMAT, credentials)[PEER_UID_INDEX]


class LinuxSingleInstanceLock:
    """取ったロックファイルと、終了の依頼を待つソケットとスレッドを持つ。SingleInstanceLock と同じメソッドを持つ。

    終了の依頼のソケットと停止のソケットの対（socket.socketpair）を専用のデーモンスレッドが select で待ち、
    QUIT_REQUEST を受けたら on_quit_requested で渡された関数を 1 回呼んでスレッドを終える（呼ぶのはそのスレッド）。
    受けたバイト列（MAX_REQUEST_BYTES まで）が HOTKEY_REQUEST_PREFIX で始まれば、続きを押されたホットキーとして on_hotkey で渡された関数に渡し、待ち続ける。
    QUIT_REQUEST・ホットキー以外を受けた接続は閉じて待ち続ける。
    抽象名前空間のソケットにはファイルの権限が効かないため、接続の相手の uid が自分と違う接続は読まずに閉じて待ち続ける。
    """

    def __init__(self, lock_fd: int, server: socket.socket) -> None:
        """取ったロックのファイル記述子と終了の依頼のソケットを受け、待つスレッドを始める。"""
        self._lock_fd = lock_fd
        self._server = server
        self._stop_reader, self._stop_writer = socket.socketpair()
        self._on_quit: Callable[[], None] | None = None
        self._quit_requested = False
        self._on_quit_called = False
        self._on_hotkey: Callable[[str], None] | None = None
        self._state_lock = threading.Lock()
        self._released = False
        self._thread = threading.Thread(target=self._wait_for_quit, name="single-instance", daemon=True)
        self._thread.start()

    def on_quit_requested(self, callback: Callable[[], None]) -> None:
        """終了を頼まれたときに呼ぶ関数を渡す。渡す前に頼まれていれば、その場で 1 回呼ぶ。"""
        with self._state_lock:
            self._on_quit = callback
            # 受け手を渡す前に頼まれていて、まだ呼んでいないか
            call_now = self._quit_requested and not self._on_quit_called
            self._on_quit_called = self._on_quit_called or call_now
        if call_now:
            callback()

    def on_hotkey(self, callback: Callable[[str], None]) -> None:
        """押されたホットキー（pynput の書式）を受けたときに呼ぶ関数を渡す（呼ぶのは待つスレッド）。前に渡した関数は置き換える。"""
        with self._state_lock:
            self._on_hotkey = callback

    def release(self) -> None:
        """待つスレッドを止め、ソケットを閉じてからロックを放す。2 回目以降は何もしない。"""
        if self._released:
            return
        self._released = True
        # 停止の合図で待つスレッドを抜けさせる（受け手の中から呼ばれたときは、そのスレッド自身を待たない）
        self._stop_writer.send(STOP_SIGNAL)
        if threading.current_thread() is not self._thread:
            self._thread.join()
        # ソケットを閉じ（抽象名前空間の名前が空く）、ロックを放す。ロックファイルは消さない（消すと、待っているプロセスと別のファイルで取り合う）
        self._server.close()
        self._stop_reader.close()
        self._stop_writer.close()
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        os.close(self._lock_fd)

    def _wait_for_quit(self) -> None:
        """終了の依頼か停止の合図が来るまで待ち、終了の依頼なら受け手を 1 回呼んで終わる。"""
        while True:
            readable, _, _ = select.select([self._server, self._stop_reader], [], [])
            # 停止の合図が来たか
            if self._stop_reader in readable:
                # はい: 受け手を呼ばずに終わる
                return
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            request = self._read_request(connection)
            # ホットキーか
            if request is not None and request.startswith(HOTKEY_REQUEST_PREFIX):
                # はい: 受け手に渡して待ち続ける
                self._dispatch_hotkey(request.removeprefix(HOTKEY_REQUEST_PREFIX).decode("utf-8", "replace"))
                continue
            # 終了の依頼か
            if request != QUIT_REQUEST:
                # いいえ: 閉じて待ち続ける
                continue
            with self._state_lock:
                self._quit_requested = True
                callback = self._on_quit
                # 受け手がまだ無い、または呼んである（2 回目以降の依頼）か
                if callback is None or self._on_quit_called:
                    # はい: ここでは呼ばない（受け手が渡されたときに呼ぶ）
                    return
                self._on_quit_called = True
            callback()
            return

    def _dispatch_hotkey(self, hotkey: str) -> None:
        """受けたホットキーを受け手に渡す。受け手が無ければ捨てる。"""
        with self._state_lock:
            callback = self._on_hotkey
        # 受け手を渡す前のホットキーは捨てる
        if callback is not None:
            callback(hotkey)

    @staticmethod
    def _read_request(connection: socket.socket) -> bytes | None:
        """同じ uid の接続から送信されたバイト列を MAX_REQUEST_BYTES まで読む。ほかの uid・読めない接続は None。接続は閉じる。"""
        with connection:
            # ほかのユーザーの接続は読まない
            if _peer_uid(connection) != os.getuid():
                return None
            connection.settimeout(CONNECTION_READ_TIMEOUT_SEC)
            try:
                return connection.recv(MAX_REQUEST_BYTES)
            except OSError:
                return None


def _request_quit(name: str) -> bool:
    """前のプロセスの終了の依頼のソケットへ接続して QUIT_REQUEST を送信する。接続できなければ False。"""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(_quit_socket_name(name))
            client.sendall(QUIT_REQUEST)
    except OSError:
        return False
    return True


def _try_lock(lock_fd: int) -> bool:
    """ロックファイルの排他を待たずに取る。取れたら True。"""
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _wait_for_release(lock_fd: int, name: str, timeout_sec: float) -> bool:
    """前のプロセスに終わるよう頼みながら、ロックが放されるのを上限まで待つ。取れたら True。

    前のプロセスがロックを取ってからソケットを作るまでの間は接続できないため、
    送信できるまで LOCK_RETRY_INTERVAL_SEC ごとに接続し直す（送信できたら以降は送信しない）。
    """
    deadline = time.monotonic() + timeout_sec
    asked = False
    while time.monotonic() < deadline:
        # まだ頼めていなければ、接続して頼む
        if not asked:
            asked = _request_quit(name)
            if asked:
                logger.info("前の常駐サービスに終わるよう頼んだ")
        time.sleep(LOCK_RETRY_INTERVAL_SEC)
        if _try_lock(lock_fd):
            return True
    if not asked:
        logger.error("前の常駐サービスの終了の依頼のソケットに上限まで接続できなかった")
    return False


def acquire_single_instance_linux(
    name: str, timeout_sec: float, *, lock_file: Path
) -> LinuxSingleInstanceLock:
    """ロックファイルを flock で取る。取られていれば終了の依頼のソケットで前のプロセスに終わるよう頼み、放されるのを待ってから取る。"""
    # 1. ロックファイルを開き（無ければ親のフォルダごと作る）、待たずに取る
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, LOCK_FILE_MODE)
    try:
        # 2. 取れたか
        if not _try_lock(lock_fd):
            # 取れない（前のプロセスが持っている）: 終わるよう頼み、放されるのを上限まで待つ
            if not _wait_for_release(lock_fd, name, timeout_sec):
                raise StartupError(f"前の常駐サービスが {timeout_sec} 秒たっても終わらない")
        # 取れた場合はそのまま進む（前のプロセスが片付けずに落ちていても、OS がロックを放している）

        # 3. 終了の依頼のソケットを bind して listen する
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(_quit_socket_name(name))
            server.listen()
        except OSError as error:
            # 同じ名前のソケットが残っている
            server.close()
            raise StartupError(f"終了の依頼のソケットを作れない（{error}）") from error
    except BaseException:
        # ロックを放してから伝える
        os.close(lock_fd)
        raise

    # 4. 終了の依頼を待つスレッドを始める
    logger.info(f"単一インスタンスを確保した（{name}）")
    return LinuxSingleInstanceLock(lock_fd, server)
