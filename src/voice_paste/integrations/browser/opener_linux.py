"""ブラウザ添付のプリセットの画面を、Chromium 系のブラウザのアプリのウィンドウ（見つからなければ既定のブラウザ）で開く。"""

from __future__ import annotations

import logging
import shutil
import subprocess
import webbrowser

from voice_paste.shared.errors import DeliveryError

logger = logging.getLogger(__name__)

LINUX_BROWSER_COMMANDS: tuple[str, ...] = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)
"""PATH から探す、`--app` を受け付けるブラウザの実行ファイル名。Ubuntu では入れ方によって名前が違い、どれか 1 つが入っていればアプリのウィンドウで開ける。"""


def open_app_window_linux(url: str) -> None:
    """URL を Chromium 系のブラウザの --app でアプリのウィンドウとして開く。無ければ既定のブラウザで開く。"""
    # 1. 並びの順で PATH から最初に見つかるブラウザを探す
    browser = next(
        (found for command in LINUX_BROWSER_COMMANDS if (found := shutil.which(command))),
        None,
    )

    # 2. 見つかった
    if browser is not None:
        # そう: --app で起動する（開いた画面の読み込みは待たない）
        try:
            subprocess.Popen([browser, f"--app={url}"])
        except OSError as error:
            raise DeliveryError(
                f"ブラウザ添付のプリセットの画面を開けませんでした（{error}）"
            ) from error
        logger.info(f"ブラウザ添付のプリセットの画面をアプリのウィンドウで開いた（{browser}・{url}）")
        return

    # 3. 見つからない: 既定のブラウザ（xdg-open）で開く
    if not webbrowser.open(url):
        # 開けるブラウザが無い
        raise DeliveryError(
            "ブラウザ添付のプリセットの画面を開けませんでした（開けるブラウザが見つかりません）"
        )
    logger.info(f"ブラウザ添付のプリセットの画面を既定のブラウザで開いた（{url}）")
