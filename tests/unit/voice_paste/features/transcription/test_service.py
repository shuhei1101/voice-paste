"""features/transcription/service.py（transcribe）の単体テスト。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

AUDIO_PATH = Path("recording.wav")


def _engine_returning(segments: list[str]) -> Callable[..., list[str]]:
    """決まった区間を返すエンジンを作る。"""

    def engine(audio_path: Path, on_progress: Callable[[float, float], None] | None = None) -> list[str]:
        """区間ごとの文字を返す。"""
        return segments

    return engine


# === transcribe ===


def test_transcribe() -> None:
    """区間を改行でつなぐ（正常系）。"""
    from voice_paste.features.transcription.service import transcribe

    # 準備
    engine = _engine_returning(["今日は", "晴れ"])

    # 実行
    text = transcribe(AUDIO_PATH, engine=engine)

    # 検証
    assert text == "今日は\n晴れ"


def test_transcribe_when_empty() -> None:
    """区間が無ければ空文字を返す（正常系）。"""
    from voice_paste.features.transcription.service import transcribe

    # 準備
    engine = _engine_returning([])

    # 実行
    text = transcribe(AUDIO_PATH, engine=engine)

    # 検証
    assert text == ""


def test_transcribe_when_engine_failed() -> None:
    """エンジンの失敗を TranscriptionError にする（異常系）。"""
    from voice_paste.features.transcription.service import transcribe
    from voice_paste.shared.errors import EngineError, TranscriptionError

    # 準備
    failure = EngineError("文字起こしワーカーが落ちた")

    def engine(audio_path: Path, on_progress: Callable[[float, float], None] | None = None) -> list[str]:
        """EngineError を送出する。"""
        raise failure

    # 実行・検証
    with pytest.raises(TranscriptionError, match="文字起こしワーカーが落ちた") as exc_info:
        transcribe(AUDIO_PATH, engine=engine)
    assert exc_info.value.__cause__ is failure


def test_transcribe_when_blank_segment() -> None:
    """区間の前後の空白と空白だけの区間を除く（正常系）。"""
    from voice_paste.features.transcription.service import transcribe

    # 準備
    engine = _engine_returning([" 今日は ", "  ", "晴れ"])

    # 実行
    text = transcribe(AUDIO_PATH, engine=engine)

    # 検証
    assert text == "今日は\n晴れ"
