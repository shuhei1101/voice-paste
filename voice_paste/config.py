"""設定読み込みモジュール。デフォルト値を定義し、.env で上書きする。"""

import shutil
from pathlib import Path

from dotenv import load_dotenv
import os

from voice_paste.constants import (
    ROOT_DIR,
    RESOURCES_DIR,
    LEGACY_ROOT_DIR,
    DEFAULT_PROMPT_FILE,
    DEFAULT_YOGO_FILE,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_DEVICE,
    DEFAULT_COMPUTE_TYPE,
    _is_frozen,
)


# ブートストラップ・移行処理は bundle 実行時のみ行う（dev モードでは
# プロジェクトルートを汚さないため）
_BOOTSTRAP_ENABLED = _is_frozen()


def _migrate_from_legacy(filename: str) -> None:
    """旧パス（exe隣）にユーザーデータがあれば新パス（%APPDATA%）へ移行する。"""
    if LEGACY_ROOT_DIR is None or LEGACY_ROOT_DIR == ROOT_DIR:
        return
    legacy = LEGACY_ROOT_DIR / filename
    current = ROOT_DIR / filename
    if legacy.exists() and not current.exists():
        try:
            shutil.move(str(legacy), str(current))
        except Exception:
            # 移行失敗時はコピーを試みる（移動元が使用中など）
            try:
                shutil.copy2(str(legacy), str(current))
            except Exception:
                pass


def _bootstrap_from_resources(filename: str) -> None:
    """バンドル同梱のデフォルトを ROOT_DIR にコピーする（未存在時のみ）。"""
    dest = ROOT_DIR / filename
    if dest.exists():
        return
    src = RESOURCES_DIR / filename
    if src.exists():
        try:
            shutil.copy2(str(src), str(dest))
        except Exception:
            pass


_env_file = ROOT_DIR / ".env"

if _BOOTSTRAP_ENABLED:
    # 旧パス（exe隣）からの移行 → バンドル同梱ファイルからのブートストラップ
    for _name in (".env", "yogo.csv", "prompt.txt"):
        _migrate_from_legacy(_name)

    # .env は .env.sample からもブートストラップ可能
    if not _env_file.exists():
        _env_sample = RESOURCES_DIR / ".env.sample"
        if not _env_sample.exists():
            _env_sample = RESOURCES_DIR.parent / ".env.sample"
        if _env_sample.exists():
            shutil.copy(_env_sample, _env_file)

    _bootstrap_from_resources("yogo.csv")
    _bootstrap_from_resources("prompt.txt")

    # history / log / cache ディレクトリも旧パスから移行
    for _dir in ("history", "log", "cache"):
        if LEGACY_ROOT_DIR is not None and LEGACY_ROOT_DIR != ROOT_DIR:
            _legacy_dir = LEGACY_ROOT_DIR / _dir
            _new_dir = ROOT_DIR / _dir
            if _legacy_dir.exists() and not _new_dir.exists():
                try:
                    shutil.move(str(_legacy_dir), str(_new_dir))
                except Exception:
                    pass
else:
    # 開発時は .env が無ければ .env.sample から作る（従来動作）
    if not _env_file.exists():
        _env_sample = ROOT_DIR / ".env.sample"
        if _env_sample.exists():
            shutil.copy(_env_sample, _env_file)

load_dotenv(_env_file, override=True)

# exe実行時: バンドル同梱の .env.sample を fallback として読み込む
# ユーザーの .env に存在しないキー（新バージョンで追加された設定）を補完する
if _BOOTSTRAP_ENABLED:
    _env_sample_fallback = RESOURCES_DIR / ".env.sample"
    if not _env_sample_fallback.exists():
        _env_sample_fallback = RESOURCES_DIR.parent / ".env.sample"
    if _env_sample_fallback.exists():
        load_dotenv(_env_sample_fallback, override=False)

# --- 文字起こしエンジン設定 ---
TRANSCRIPTION_ENGINE: str = os.getenv("TRANSCRIPTION_ENGINE", "local")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# --- Whisper モデル設定 ---
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", DEFAULT_WHISPER_MODEL)
WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", DEFAULT_DEVICE)
WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", DEFAULT_COMPUTE_TYPE)
WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "0"))
WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "10"))
WHISPER_BEST_OF: int = int(os.getenv("WHISPER_BEST_OF", "5"))
WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "ja")
WHISPER_VAD_FILTER: bool = os.getenv("WHISPER_VAD_FILTER", "true").lower() == "true"
WHISPER_VAD_THRESHOLD: float = float(os.getenv("WHISPER_VAD_THRESHOLD", "0.5"))
WHISPER_VAD_MIN_SPEECH_MS: int = int(os.getenv("WHISPER_VAD_MIN_SPEECH_MS", "250"))
WHISPER_VAD_MIN_SILENCE_MS: int = int(os.getenv("WHISPER_VAD_MIN_SILENCE_MS", "2000"))
WHISPER_CONDITION_ON_PREVIOUS_TEXT: bool = (
    os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
)
WHISPER_TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
WHISPER_NO_SPEECH_THRESHOLD: float = float(
    os.getenv("WHISPER_NO_SPEECH_THRESHOLD", "0.6")
)

def _resolve_user_file(env_value: str | None, filename: str, default: Path) -> Path:
    """ユーザー編集ファイルのパスを解決する。

    優先順:
      1. 環境変数が絶対パス → そのまま使用
      2. ROOT_DIR / ファイル名（%APPDATA%\\voice-paste 配下を最優先）
      3. 環境変数が相対パス → ROOT_DIR / 相対パス
      4. RESOURCES_DIR / ファイル名（バンドル同梱のデフォルト）
      5. default
    """
    root_candidate = ROOT_DIR / filename
    if env_value:
        p = Path(env_value)
        if p.is_absolute():
            return p
        if root_candidate.exists():
            return root_candidate
        rel_candidate = ROOT_DIR / p
        if rel_candidate.exists():
            return rel_candidate
        bundled = RESOURCES_DIR / p.name
        if bundled.exists():
            return bundled
        return root_candidate
    if root_candidate.exists():
        return root_candidate
    return default


# --- プロンプトファイル ---
PROMPT_FILE: Path = _resolve_user_file(
    os.getenv("PROMPT_FILE"), "prompt.txt", DEFAULT_PROMPT_FILE,
)

# --- 用語集CSVファイル ---
YOGO_FILE: Path = _resolve_user_file(
    os.getenv("YOGO_FILE"), "yogo.csv", DEFAULT_YOGO_FILE,
)

# --- 動作設定 ---

# --- ログ設定 ---
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# --- 常駐モード設定 ---
RESIDENT_MODE: bool = os.getenv("RESIDENT_MODE", "true").lower() == "true"
RESIDENT_HOTKEY: str = os.getenv("RESIDENT_HOTKEY", "<ctrl>+<alt>+d")
CONFIRM_HOTKEY: str = os.getenv("CONFIRM_HOTKEY", "<ctrl>+<alt>+d")
CONFIRM_PASTE_ONLY_HOTKEY: str = os.getenv("CONFIRM_PASTE_ONLY_HOTKEY", "<ctrl>+<alt>+v")
CANCEL_HOTKEY: str = os.getenv("CANCEL_HOTKEY", "<ctrl>+<alt>+q")
COPY_ONLY_HOTKEY: str = os.getenv("COPY_ONLY_HOTKEY", "<ctrl>+<alt>+c")
PAUSE_HOTKEY: str = os.getenv("PAUSE_HOTKEY", "<ctrl>+<alt>+z")

# 貼り付けキー（ターミナルなど Ctrl+Shift+V が必要なアプリ向け）
PASTE_KEY: str = os.getenv("PASTE_KEY", "<ctrl>+v")

# 貼付から送信(Enter)までの待機秒数（アプリによってはペースト直後のEnterが無視されるため）
PASTE_ENTER_DELAY: float = float(os.getenv("PASTE_ENTER_DELAY", "0.5"))

# --- AI送信設定 ---
# AI_SEND_1_NAME / AI_SEND_1_URL / AI_SEND_1_HOTKEY, ... で複数設定可
AI_SEND_DELAY: float = float(os.getenv("AI_SEND_DELAY", "3.0"))
AI_SEND_APPS: list[dict[str, str]] = []
_ai_idx = 1
while True:
    _name = os.getenv(f"AI_SEND_{_ai_idx}_NAME", "").strip()
    _url = os.getenv(f"AI_SEND_{_ai_idx}_URL", "").strip()
    if not _name or not _url:
        break
    _hotkey = os.getenv(f"AI_SEND_{_ai_idx}_HOTKEY", f"<ctrl>+<alt>+{_ai_idx}").strip()
    _enabled = os.getenv(f"AI_SEND_{_ai_idx}_ENABLED", "true").lower() == "true"
    AI_SEND_APPS.append({"name": _name, "url": _url, "hotkey": _hotkey, "enabled": str(_enabled).lower()})
    _ai_idx += 1

# --- 履歴設定 ---
HISTORY_ENABLED: bool = os.getenv("HISTORY_ENABLED", "true").lower() == "true"
HISTORY_RETENTION_DAYS: int = int(os.getenv("HISTORY_RETENTION_DAYS", "1"))

# --- ウィンドウ設定 ---
WINDOW_TOPMOST: bool = os.getenv("WINDOW_TOPMOST", "true").lower() == "true"
# 表示位置: center / top-left / top-right / bottom-left / bottom-right
WINDOW_POSITION: str = os.getenv("WINDOW_POSITION", "center")
# カーソルがあるモニターに表示する（デュアルモニター対応）
WINDOW_FOLLOW_CURSOR: bool = os.getenv("WINDOW_FOLLOW_CURSOR", "true").lower() == "true"
# ウィンドウを表示せずトレイアイコンだけで状態表示する
WINDOW_HIDDEN: bool = os.getenv("WINDOW_HIDDEN", "false").lower() == "true"
# 波形の感度（大きいほど小さい声でも波形が大きく振れる）
WAVE_GAIN: float = float(os.getenv("WAVE_GAIN", "50"))
