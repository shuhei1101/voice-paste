"""カスタム例外クラス定義モジュール。"""


class VoicePasteError(Exception):
    """voice-paste 基底例外クラス。"""


class RecordingError(VoicePasteError):
    """音声録音に関するエラー。"""


class TranscriptionError(VoicePasteError):
    """文字起こし処理に関するエラー。"""


class ClipboardError(VoicePasteError):
    """クリップボード操作に関するエラー。"""


class ConfigError(VoicePasteError):
    """設定読み込みに関するエラー。"""
