"""実機の非機能要件テストが使う、固めた文字起こしの設定と録音・用語集（`tests/nfr/fixtures/`、git 管理外）の読み込み。"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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

QUOTES = ("'", '"')
"""固めた設定の値を囲んでよい引用符。"""

MIN_QUOTED_LENGTH = 2
"""引用符で囲まれた値の最短の長さ（開きと閉じの 2 文字）。"""


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


def _read_env_values(path: Path) -> dict[str, str]:
    """`KEY=VALUE` の行を key と value の辞書にして返す（空行と `#` で始まる行は飛ばし、値が同じ種類の引用符で囲まれていれば外す）。"""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # 空行とコメントの行は読まない
        if not stripped or stripped.startswith("#"):
            continue
        # 最初の `=` で key と value に分ける
        key, _, value = stripped.partition("=")
        value = value.strip()
        # 同じ種類の引用符で囲まれた値は、引用符を外す
        if len(value) >= MIN_QUOTED_LENGTH and value[0] == value[-1] and value[0] in QUOTES:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_local_whisper_settings() -> LocalWhisperSettings:
    """固めた設定（whisper.env）を、ローカルの Whisper の設定にして返す。"""
    from voice_paste.shared.settings import LocalWhisperSettings

    from tests.support.settings import load_test_default_settings

    # 既定の設定に、固めた値を重ねる
    env_values = _read_env_values(WHISPER_ENV_FILE)
    defaults = load_test_default_settings().transcription.local_whisper
    return LocalWhisperSettings.model_validate(
        {
            **defaults.model_dump(),
            **{
                field: parse(env_values[key])
                for key, (field, parse) in LOCAL_WHISPER_FIELDS.items()
            },
        }
    )


def local_whisper_yaml() -> str:
    """固めた設定を、settings.yaml の `transcription.local_whisper` の表にして返す（常駐サービスの起動へ追加する設定）。"""
    lines = ["transcription:", "  local_whisper:"]
    for key, value in load_local_whisper_settings().model_dump().items():
        # JSON の書き方の値は、そのまま YAML の値として読める
        literal = json.dumps(value)
        lines.append(f"    {key}: {literal}")
    return "\n".join(lines) + "\n"
