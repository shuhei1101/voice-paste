"""同じ引数で常駐アプリを起動し直す。"""

from __future__ import annotations

import logging
import subprocess
import sys

from voice_paste.shared.os_kind import OsKind

logger = logging.getLogger(__name__)

DETACHED_PROCESS: int = 0x00000008
"""親のコンソールから切り離すフラグ。Windows で relaunch が渡す subprocess.DETACHED_PROCESS の値（Linux の subprocess には属性が無い）。"""

CREATE_NEW_PROCESS_GROUP: int = 0x00000200
"""新しいプロセスグループで起動するフラグ。DETACHED_PROCESS と同じ理由で値を持つ。"""


def relaunch(argv: list[str], *, os_kind: OsKind) -> None:
    """同じ Python と引数で `python -m voice_paste` を切り離したプロセスとして起動する。

    片付けを終えた後に呼ぶ（API のポートとエンジンを放してから次を立てる）。起動できなくても例外は漏らさない。
    """
    command = [sys.executable, "-m", "voice_paste", *argv]
    try:
        # OS に合わせて切り離して起動する
        if os_kind is OsKind.WINDOWS:
            subprocess.Popen(  # noqa: S603 引数は配列で渡し、シェルを通さない
                command,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            subprocess.Popen(  # noqa: S603 引数は配列で渡し、シェルを通さない
                command,
                start_new_session=True,
                close_fds=True,
            )
    except OSError:
        logger.exception("起動し直せなかった")
        return
    logger.info(f"起動し直した（{' '.join(argv)}）")
