"""外部ライブラリのモック返却値定義モジュール。"""

# faster-whisper の transcribe() 返却値モック
MOCK_TRANSCRIPTION_TEXT = "これはテスト用の文字起こし結果です。"


class MockSegment:
    """WhisperModel.transcribe() が返すセグメントのモック。"""

    def __init__(self, text: str) -> None:
        self.text = text


class MockTranscriptionInfo:
    """WhisperModel.transcribe() が返す info のモック。"""

    language = "ja"
    language_probability = 0.99


MOCK_SEGMENTS = [MockSegment(MOCK_TRANSCRIPTION_TEXT)]
MOCK_INFO = MockTranscriptionInfo()
