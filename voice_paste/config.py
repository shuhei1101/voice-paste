"""設定読み込みモジュール。デフォルト値を定義し、.env で上書きする。"""

import shutil
from pathlib import Path

from dotenv import load_dotenv
import os

from voice_paste.constants import (
    ROOT_DIR,
    DEFAULT_PROMPT_FILE,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_DEVICE,
    DEFAULT_COMPUTE_TYPE,
)

# .env が存在しない場合は .env.sample からコピー
_env_file = ROOT_DIR / ".env"
_env_sample = ROOT_DIR / ".env.sample"
if not _env_file.exists() and _env_sample.exists():
    shutil.copy(_env_sample, _env_file)

load_dotenv(_env_file)

# --- Whisper モデル設定 ---
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)
WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", DEFAULT_DEVICE)
WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", DEFAULT_COMPUTE_TYPE)
WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "0"))
WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "ja")
WHISPER_VAD_FILTER: bool = os.getenv("WHISPER_VAD_FILTER", "true").lower() == "true"
WHISPER_CONDITION_ON_PREVIOUS_TEXT: bool = (
    os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
)
WHISPER_TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
WHISPER_NO_SPEECH_THRESHOLD: float = float(
    os.getenv("WHISPER_NO_SPEECH_THRESHOLD", "0.6")
)

# --- プロンプトファイル ---
PROMPT_FILE: Path = Path(os.getenv("PROMPT_FILE", str(DEFAULT_PROMPT_FILE)))

# --- 動作設定 ---
AUTO_PASTE: bool = os.getenv("AUTO_PASTE", "true").lower() == "true"
AUTO_ENTER: bool = os.getenv("AUTO_ENTER", "true").lower() == "true"

# --- ログ設定 ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
