"""アプリ名と、設定の 3 レイヤー・履歴・ログ・一時の音声・トークン・ロックファイルの置き場所のパス。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME: str = "voice-paste"
"""置き場所のフォルダ名に使うアプリの名前。"""

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
"""config/defaults.yaml と settings.local.yaml を引く、リポジトリの直下のフォルダ。"""

DEFAULTS_DIR_NAME: str = "config"
"""リポジトリの直下で、既定値のファイルを置くフォルダの名前。"""

DEFAULTS_FILE_NAME: str = "defaults.yaml"
"""既定値のファイルの名前。"""

SETTINGS_FILE_NAME: str = "settings.yaml"
"""設定のフォルダ（data_dir）に置く、環境の値のファイルの名前。"""

LOCAL_SETTINGS_FILE_NAME: str = "settings.local.yaml"
"""リポジトリの直下に置く、checkout の上書きのファイルの名前（git の管理から外す）。"""

LEGACY_SETTINGS_FILE_NAME: str = "settings.toml"
"""前のバージョンの設定のファイルの名前。settings.yaml が無いときに移す元。"""

HISTORY_DIR_NAME: str = "history"
"""履歴のフォルダの名前。"""

LOG_DIR_NAME: str = "log"
"""ログのフォルダの名前。"""

TMP_DIR_NAME: str = "tmp"
"""履歴を残さないときの一時の音声のフォルダの名前。"""

TOKEN_FILE_NAME: str = "api_token"
"""起動ごとのトークンとポートを書くファイルの名前。"""

UI_IMAGE_DIR_NAME: str = "ui"
"""画面の画像（選択欄の開くマーカーの SVG）のフォルダの名前。"""

LOCK_FILE_NAME: str = "instance.lock"
"""Linux の単一インスタンスのロックファイルの名前。"""

SECRETS_DIR_NAME: str = "secrets"
"""設定ファイルと同じフォルダの下にある、秘匿の値のファイルのフォルダの名前。"""

OPENAI_API_KEY_FILE_NAME: str = "openai_api_key"
"""OpenAI の API キーを置くファイルの名前。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class AppPaths:
    """設定の 3 レイヤーのファイル・settings.toml・OpenAI の API キーのファイル・履歴・ログ・一時の音声・トークン・画面の画像・ロックファイルの置き場所。"""

    defaults_file: Path
    """設定の既定値（`{REPO_ROOT}/config/defaults.yaml`）。"""
    settings_file: Path
    """環境の値（settings.yaml）。設定画面の保存が書く。"""
    local_settings_file: Path | None
    """checkout の上書き（`{REPO_ROOT}/settings.local.yaml`）。データの置き場所を渡したときは None で、読まない。"""
    legacy_settings_file: Path
    """前のバージョンの設定（settings.toml）。settings_file が無いときに移す元。"""
    openai_api_key_file: Path
    """OpenAI の API キーのファイル。設定ファイルと同じフォルダの下で、ユーザーが置き、読むだけで作らない。"""
    history_dir: Path
    log_dir: Path
    tmp_dir: Path
    token_file: Path
    ui_image_dir: Path
    lock_file: Path
    """Linux の単一インスタンスのロックファイル。Windows では使わない。"""


def resolve_app_paths(data_dir: Path | None) -> AppPaths:
    """データの置き場所が渡されればその下、無ければ platformdirs で引いた置き場所で AppPaths を作る。"""
    # データの置き場所が渡されているか
    if data_dir is not None:
        # ある: 既定値の他は全てをその下に置き、checkout の上書きを読まない（並走の間に普段使いの置き場所と手元の settings.local.yaml へ触れない）
        config_root = data_dir
        data_root = data_dir
        local_settings_file = None
    else:
        # 無い: 設定は roaming の置き場所、それ以外はローカルの置き場所。checkout の上書きはリポジトリの直下
        config_root = Path(user_config_dir(APP_NAME, appauthor=False, roaming=True))
        data_root = Path(user_data_dir(APP_NAME, appauthor=False))
        local_settings_file = REPO_ROOT / LOCAL_SETTINGS_FILE_NAME

    return AppPaths(
        defaults_file=REPO_ROOT / DEFAULTS_DIR_NAME / DEFAULTS_FILE_NAME,
        settings_file=config_root / SETTINGS_FILE_NAME,
        local_settings_file=local_settings_file,
        legacy_settings_file=config_root / LEGACY_SETTINGS_FILE_NAME,
        openai_api_key_file=config_root / SECRETS_DIR_NAME / OPENAI_API_KEY_FILE_NAME,
        history_dir=data_root / HISTORY_DIR_NAME,
        log_dir=data_root / LOG_DIR_NAME,
        tmp_dir=data_root / TMP_DIR_NAME,
        token_file=data_root / TOKEN_FILE_NAME,
        ui_image_dir=data_root / UI_IMAGE_DIR_NAME,
        lock_file=data_root / LOCK_FILE_NAME,
    )
