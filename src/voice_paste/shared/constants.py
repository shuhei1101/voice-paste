"""アプリ名と、設定・履歴・ログ・一時の音声・トークンの置き場所のパス。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME: str = "voice-paste"
"""置き場所のフォルダ名に使うアプリの名前。"""

SETTINGS_FILE_NAME: str = "settings.toml"
"""設定ファイルの名前。"""

HISTORY_DIR_NAME: str = "history"
"""履歴のフォルダの名前。"""

LOG_DIR_NAME: str = "log"
"""ログのフォルダの名前。"""

TMP_DIR_NAME: str = "tmp"
"""履歴を残さないときの一時の音声のフォルダの名前。"""

TOKEN_FILE_NAME: str = "api_token"
"""起動ごとのトークンとポートを書くファイルの名前。"""

UI_IMAGE_DIR_NAME: str = "ui"
"""画面の画像（選択欄の開く印の SVG）のフォルダの名前。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class AppPaths:
    """設定・履歴・ログ・一時の音声・トークン・画面の画像の置き場所。"""

    settings_file: Path
    history_dir: Path
    log_dir: Path
    tmp_dir: Path
    token_file: Path
    ui_image_dir: Path


def resolve_app_paths(data_dir: Path | None) -> AppPaths:
    """データの置き場所が渡されればその下、無ければ platformdirs で引いた置き場所で AppPaths を作る。"""
    # データの置き場所が渡されているか
    if data_dir is not None:
        # ある: 全てをその下に置く（並走の間に普段使いの置き場所へ触れない）
        config_root = data_dir
        data_root = data_dir
    else:
        # 無い: 設定は roaming の置き場所、それ以外はローカルの置き場所
        config_root = Path(user_config_dir(APP_NAME, appauthor=False, roaming=True))
        data_root = Path(user_data_dir(APP_NAME, appauthor=False))

    return AppPaths(
        settings_file=config_root / SETTINGS_FILE_NAME,
        history_dir=data_root / HISTORY_DIR_NAME,
        log_dir=data_root / LOG_DIR_NAME,
        tmp_dir=data_root / TMP_DIR_NAME,
        token_file=data_root / TOKEN_FILE_NAME,
        ui_image_dir=data_root / UI_IMAGE_DIR_NAME,
    )
