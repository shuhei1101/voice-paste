"""実機の非機能要件テストが使う、固めた文字起こしの設定と録音・用語集（`tests/nfr/fixtures/`、git 管理外）の読み込み。"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dotenv import dotenv_values

if TYPE_CHECKING:
    from voice_paste.shared.settings import LocalWhisperSettings

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "nfr" / "fixtures"
RECORDINGS_DIR = FIXTURES_DIR / "recordings"
YOGO_FILE = FIXTURES_DIR / "yogo.csv"
WHISPER_ENV_FILE = FIXTURES_DIR / "whisper.env"

PASTE_LATENCY_RECORDING = RECORDINGS_DIR / "latency" / "20261002212623.wav"
"""話し終えてから貼り付くまでの時間を測る録音（先頭 10 秒を使う）。刷新前を測り直したのと同じ録音。特性テストが拾わないよう `recordings/latency/` に置く。"""

WORKER_READY_TIMEOUT_SEC = 27.0
"""非機能要件の文字起こしワーカーの立て直しの時間の決定値。"""

WORKER_STOP_TIMEOUT_SEC = 2.0
"""非機能要件の文字起こしワーカーの終わりを待つ時間の決定値。"""


def _to_bool(value: str) -> bool:
    """true / false の文字を bool にする（刷新前の config.py と同じ規則）。"""
    return value.lower() == "true"


LOCAL_WHISPER_FIELDS: dict[str, tuple[str, Callable[[str], object]]] = {
    "WHISPER_MODEL": ("model", str),
    "WHISPER_DEVICE": ("device", str),
    "WHISPER_COMPUTE_TYPE": ("compute_type", str),
    "WHISPER_CPU_THREADS": ("cpu_threads", int),
    "WHISPER_NUM_WORKERS": ("num_workers", int),
    "WHISPER_BEAM_SIZE": ("beam_size", int),
    "WHISPER_BEST_OF": ("best_of", int),
    "WHISPER_LANGUAGE": ("language", str),
    "WHISPER_VAD_FILTER": ("vad_filter", _to_bool),
    "WHISPER_VAD_THRESHOLD": ("vad_threshold", float),
    "WHISPER_VAD_MIN_SPEECH_MS": ("vad_min_speech_ms", int),
    "WHISPER_VAD_MIN_SILENCE_MS": ("vad_min_silence_ms", int),
    "WHISPER_CONDITION_ON_PREVIOUS_TEXT": ("condition_on_previous_text", _to_bool),
    "WHISPER_TEMPERATURE": ("temperature", float),
    "WHISPER_NO_SPEECH_THRESHOLD": ("no_speech_threshold", float),
}
"""固めた設定（whisper.env の変数）と、対応する LocalWhisperSettings の項目・型への変換。"""

requires_real_whisper = pytest.mark.skipif(
    not WHISPER_ENV_FILE.exists() or sys.platform != "win32" or shutil.which("nvidia-smi") is None,
    reason="Windows の NVIDIA GPU と、tests/nfr/fixtures/ の固めた設定（whisper.env）が要る",
)
"""固めた設定・GPU が無い環境で、ローカルの Whisper を使う実機のテストを skip するマーカー。"""


def load_local_whisper_settings() -> LocalWhisperSettings:
    """固めた設定（whisper.env）を、ローカルの Whisper の設定にして返す。"""
    from voice_paste.shared.settings import LocalWhisperSettings

    env_values = dotenv_values(WHISPER_ENV_FILE)
    return LocalWhisperSettings(
        **{
            field: parse(env_values[key] or "")
            for key, (field, parse) in LOCAL_WHISPER_FIELDS.items()
        }
    )


def local_whisper_toml() -> str:
    """固めた設定を、settings.toml の `[transcription.local_whisper]` の表にして返す（常駐サービスの起動へ足す設定）。"""
    lines = ["[transcription.local_whisper]"]
    for key, value in load_local_whisper_settings().model_dump().items():
        # TOML の真偽値は小文字。文字列と数値は JSON の書き方と同じで書ける
        literal = json.dumps(value)
        lines.append(f"{key} = {literal}")
    return "\n".join(lines) + "\n"
