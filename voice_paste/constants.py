"""定数定義モジュール。"""

import sys
from pathlib import Path


def _is_frozen() -> bool:
    """PyInstaller などでバンドル実行中かどうか判定する。"""
    return getattr(sys, "frozen", False)


# リソースディレクトリ（読み取り専用）: 開発時はソースツリー、bundle時は _MEIPASS を参照
if _is_frozen():
    # PyInstaller 実行時: _MEIPASS が展開先ディレクトリ
    _BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # 書き込み可能ディレクトリは exe の隣に配置
    _WRITABLE_ROOT = Path(sys.executable).parent
    RESOURCES_DIR = _BUNDLE_DIR / "resources"
    ROOT_DIR = _WRITABLE_ROOT
else:
    ROOT_DIR = Path(__file__).parent.parent
    RESOURCES_DIR = ROOT_DIR / "resources"

# ログディレクトリ（書き込み先）
LOG_DIR = ROOT_DIR / "log"

# デフォルトのプロンプトファイルパス
DEFAULT_PROMPT_FILE = RESOURCES_DIR / "prompt.txt"

# デフォルトの用語集CSVファイルパス
DEFAULT_YOGO_FILE = RESOURCES_DIR / "yogo.csv"

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
