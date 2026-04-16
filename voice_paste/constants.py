"""定数定義モジュール。"""

VERSION = "1.0.0"

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """PyInstaller などでバンドル実行中かどうか判定する。"""
    return getattr(sys, "frozen", False)


# リソースディレクトリ（読み取り専用）: 開発時はソースツリー、bundle時は _MEIPASS を参照
# ROOT_DIR（書き込み可能）: 開発時はプロジェクトルート、bundle時は %APPDATA%\voice-paste
if _is_frozen():
    _BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    RESOURCES_DIR = _BUNDLE_DIR / "resources"
    # ユーザー設定は %APPDATA%\voice-paste に配置
    # （exe 隣だとアプリ更新時にユーザーデータが消えるため）
    _appdata = os.getenv("APPDATA")
    if _appdata:
        ROOT_DIR = Path(_appdata) / "voice-paste"
    else:
        # APPDATA が取れない環境では従来どおり exe の隣
        ROOT_DIR = Path(sys.executable).parent
    ROOT_DIR.mkdir(parents=True, exist_ok=True)
    # exe の隣（旧パス）: 旧バージョンから移行するために保持
    LEGACY_ROOT_DIR: Path | None = Path(sys.executable).parent
else:
    ROOT_DIR = Path(__file__).parent.parent
    RESOURCES_DIR = ROOT_DIR / "resources"
    LEGACY_ROOT_DIR = None

# ログディレクトリ（書き込み先）
LOG_DIR = ROOT_DIR / "log"

# デフォルトのプロンプトファイルパス
# bundle時: %APPDATA%\voice-paste\prompt.txt（編集可）
# 開発時: resources/prompt.txt
DEFAULT_PROMPT_FILE = ROOT_DIR / "prompt.txt" if _is_frozen() else RESOURCES_DIR / "prompt.txt"

# デフォルトの用語集CSVファイルパス
# bundle時: %APPDATA%\voice-paste\yogo.csv（編集可）
# 開発時: resources/yogo.csv
DEFAULT_YOGO_FILE = ROOT_DIR / "yogo.csv" if _is_frozen() else RESOURCES_DIR / "yogo.csv"

# デフォルトのアイコンファイルパス（トレイアイコン用）
DEFAULT_ICON_FILE = RESOURCES_DIR / "icon.png"

# デフォルトの音声ファイル保存先（一時ファイル。書き込み先）
DEFAULT_AUDIO_TMP = ROOT_DIR / "cache" / "recording.wav"

# 履歴保存ディレクトリ
HISTORY_DIR = ROOT_DIR / "history"

# デフォルトのWhisperモデル
DEFAULT_WHISPER_MODEL = "large-v3"

# デフォルトのデバイス
DEFAULT_DEVICE = "cuda"

# デフォルトの量子化タイプ
DEFAULT_COMPUTE_TYPE = "float16"

# サンプリングレート（Hz）
SAMPLE_RATE = 16000
