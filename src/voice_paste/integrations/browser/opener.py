"""AI チャットの画面を、Microsoft Edge のアプリのウィンドウ（見つからなければ既定のブラウザ）で開く。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from voice_paste.shared.errors import DeliveryError

logger = logging.getLogger(__name__)

EDGE_COMMAND: str = "msedge"
"""PATH から探す Edge の実行ファイル名。"""

EDGE_PATHS: tuple[str, ...] = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
"""PATH に Edge が無いときに探す、Edge の既定の置き場所。"""


def _find_edge() -> str | None:
    """Edge の実行ファイルを PATH、既定の置き場所の順に探す。無ければ None。"""
    found = shutil.which(EDGE_COMMAND)
    if found is not None:
        return found
    return next((path for path in EDGE_PATHS if Path(path).exists()), None)


def open_app_window(url: str) -> None:
    """URL を Edge の --app でアプリのウィンドウとして開く。Edge が無ければ既定のブラウザで開く。"""
    # 1. Edge の実行ファイルを探す
    edge = _find_edge()

    # 2. 見つかれば Edge の --app で、見つからなければ既定のブラウザで開く（開いた画面の読み込みは待たない）
    try:
        if edge is not None:
            subprocess.Popen([edge, f"--app={url}"])
        else:
            os.startfile(url)  # type: ignore[attr-defined] # Windows にだけある
    except OSError as error:
        raise DeliveryError(f"AI チャットの画面を開けませんでした（{error}）") from error

    if edge is not None:
        logger.info(f"AI チャットを Edge のアプリのウィンドウで開いた（{url}）")
    else:
        logger.info(f"AI チャットを既定のブラウザで開いた（{url}）")
