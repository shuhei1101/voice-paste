"""Linux の GNOME のセッション（Xorg・Wayland）で、gnome-session-inhibit の子プロセスにより録音の間のアイドル（画面の消灯）を抑止する。

子プロセスの `cat` が標準入力のパイプを読んでいる間だけ抑止が続き、パイプが閉じると（解除・常駐アプリの終了・強制終了のどれでも）解ける。
"""

from __future__ import annotations

import logging
import subprocess
import threading

from voice_paste.shared.errors import DisplayInhibitError

logger = logging.getLogger(__name__)

INHIBIT_COMMAND: tuple[str, ...] = (
    "gnome-session-inhibit",
    "--inhibit",
    "idle",
    "--app-id",
    "voice-paste",
    "--reason",
    "recording",
    "cat",
)
"""gnome-session のアイドルを抑止し、標準入力のパイプが閉じるまで続ける子プロセス。`--inhibit-only` は自分から終わらず、常駐アプリの異常終了で抑止が残るため使用しない。"""

RELEASE_WAIT_SEC: float = 2.0
"""パイプを閉じた後に子プロセスの終わりを待つ上限（秒）。過ぎたら強制終了する。"""

# 子プロセスを守るロック
_lock = threading.Lock()
# 抑止の子プロセス。抑止していなければ None（inhibit_display_linux と release_display_linux だけが触る）
_process: subprocess.Popen[bytes] | None = None


def inhibit_display_linux() -> None:
    """抑止の子プロセスを起動する。抑止中なら何もしない。"""
    global _process
    with _lock:
        # 1. 抑止は 1 つだけ持つ
        if _process is not None and _process.poll() is None:
            return

        # 2. 標準入力をパイプにして起動する（stderr は子プロセスが終わった後に理由として読む）
        try:
            _process = subprocess.Popen(  # noqa: S603 固定のコマンドで、引数に外の値を含めない
                INHIBIT_COMMAND,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise DisplayInhibitError(f"gnome-session-inhibit を起動できなかった（{error}）") from error


def release_display_linux() -> None:
    """抑止の子プロセスを終わらせる。先に終わっていれば、抑止できていなかったとして DisplayInhibitError を送出する。"""
    global _process
    with _lock:
        if _process is None:
            return
        process = _process
        _process = None

        # 1. 先に終わっていれば、GNOME のセッションでない等で抑止できていなかった
        returncode = process.poll()
        if returncode is not None:
            stderr = process.stderr.read().decode(errors="replace").strip() if process.stderr else ""
            raise DisplayInhibitError(
                f"gnome-session-inhibit が先に終わっていた（終了コード {returncode}・{stderr}）"
            )

        # 2. パイプを閉じて終わりを待ち、終わらなければ強制終了する
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(RELEASE_WAIT_SEC)
        except subprocess.TimeoutExpired:
            logger.warning("画面の消灯の抑止の子プロセスが終わらず強制終了した")
            process.kill()
            process.wait()
