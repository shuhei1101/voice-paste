"""WhisperTranscriber の統合テスト。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.mocks.mock_externals import MOCK_SEGMENTS, MOCK_INFO, MOCK_TRANSCRIPTION_TEXT


@pytest.fixture
def mock_whisper_model():
    """WhisperModel をモック化するフィクスチャ。"""
    with patch("voice_paste.transcription.whisper_transcriber.WhisperModel") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = (MOCK_SEGMENTS, MOCK_INFO)
        mock_cls.return_value = mock_instance
        yield mock_instance


def test_transcribe_returns_text(mock_whisper_model, tmp_path: Path) -> None:
    """文字起こし結果が正しく返されることを確認する。"""
    from voice_paste.transcription.whisper_transcriber import WhisperTranscriber

    # ダミー音声ファイルを作成
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"dummy")

    transcriber = WhisperTranscriber()
    result = transcriber.transcribe(audio_file, prompt="テスト用プロンプト")

    assert result == MOCK_TRANSCRIPTION_TEXT
    mock_whisper_model.transcribe.assert_called_once()


def test_transcribe_with_empty_prompt(mock_whisper_model, tmp_path: Path) -> None:
    """プロンプトが空の場合、initial_prompt=None で呼ばれることを確認する。"""
    from voice_paste.transcription.whisper_transcriber import WhisperTranscriber

    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"dummy")

    transcriber = WhisperTranscriber()
    transcriber.transcribe(audio_file, prompt="")

    call_kwargs = mock_whisper_model.transcribe.call_args.kwargs
    assert call_kwargs.get("initial_prompt") is None
