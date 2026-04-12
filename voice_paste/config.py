"""設定読み込みモジュール。デフォルト値を定義し、.env で上書きする。"""

import shutil
from pathlib import Path

from dotenv import load_dotenv
import os

from voice_paste.constants import (
    ROOT_DIR,
    RESOURCES_DIR,
    DEFAULT_PROMPT_FILE,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_DEVICE,
    DEFAULT_COMPUTE_TYPE,
)

# .env は書き込み可能な ROOT_DIR 配下を参照する（bundle時は exe の隣）
_env_file = ROOT_DIR / ".env"
_env_sample = ROOT_DIR / ".env.sample"
# bundle 実行時、exe の隣に .env.sample が無ければ RESOURCES_DIR 側を探す
if not _env_sample.exists():
    _bundled_sample = RESOURCES_DIR.parent / ".env.sample"
    if _bundled_sample.exists():
        _env_sample = _bundled_sample
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
# 相対パス指定の場合、bundle時は RESOURCES_DIR ベースで解決する
_prompt_env = os.getenv("PROMPT_FILE")
if _prompt_env:
    _prompt_path = Path(_prompt_env)
    if not _prompt_path.is_absolute():
        # 開発時は ROOT_DIR からの相対、bundle時は RESOURCES_DIR の親から解決
        _candidate = ROOT_DIR / _prompt_path
        if not _candidate.exists() and (RESOURCES_DIR / _prompt_path.name).exists():
            _candidate = RESOURCES_DIR / _prompt_path.name
        _prompt_path = _candidate
    PROMPT_FILE: Path = _prompt_path
else:
    PROMPT_FILE = DEFAULT_PROMPT_FILE

# --- 動作設定 ---

# --- ログ設定 ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- 常駐モード設定 ---
RESIDENT_MODE: bool = os.getenv("RESIDENT_MODE", "true").lower() == "true"
RESIDENT_HOTKEY: str = os.getenv("RESIDENT_HOTKEY", "<ctrl>+<alt>+v")
CONFIRM_HOTKEY: str = os.getenv("CONFIRM_HOTKEY", "<ctrl>+<alt>+v")
CONFIRM_PASTE_ONLY_HOTKEY: str = os.getenv("CONFIRM_PASTE_ONLY_HOTKEY", "<alt>+<ctrl>+<shift>+v")
CANCEL_HOTKEY: str = os.getenv("CANCEL_HOTKEY", "<ctrl>+<alt>+c")
