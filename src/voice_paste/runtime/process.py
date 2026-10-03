"""同じ引数で常駐アプリを起動し直す。"""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def relaunch(argv: list[str]) -> None:
    """同じ Python と引数で `python -m voice_paste` を切り離したプロセスとして起動する。

    片付けを終えた後に呼ぶ（API のポートとエンジンを放してから次を立てる）。起動できなくても例外は漏らさない。
    """
    try:
        subprocess.Popen(  # noqa: S603 引数は配列で渡し、シェルを通さない
            [sys.executable, "-m", "voice_paste", *argv],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError:
        logger.exception("起動し直せなかった")
        return
    logger.info(f"起動し直した（{' '.join(argv)}）")
