"""定数定義モジュール。"""

from pathlib import Path

# プロジェクトルートパス
ROOT_DIR = Path(__file__).parent.parent

# リソースディレクトリ
RESOURCES_DIR = ROOT_DIR / "resources"

# ログディレクトリ
LOG_DIR = ROOT_DIR / "log"

# デフォルトのプロンプトファイルパス
DEFAULT_PROMPT_FILE = RESOURCES_DIR / "prompt.txt"

# デフォルトの音声ファイル保存先（一時ファイル）
DEFAULT_AUDIO_TMP = ROOT_DIR / "cache" / "recording.wav"

# デフォルトのWhisperモデル
DEFAULT_WHISPER_MODEL = "large-v3"

# デフォルトのデバイス
DEFAULT_DEVICE = "cuda"

# デフォルトの量子化タイプ
DEFAULT_COMPUTE_TYPE = "float16"

# サンプリングレート（Hz）
SAMPLE_RATE = 16000
