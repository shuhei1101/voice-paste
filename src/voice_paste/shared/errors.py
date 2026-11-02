"""このアプリが送出する例外の階層。"""

from __future__ import annotations

from pathlib import Path


class AppError(Exception):
    """このアプリが送出する例外の根。"""


class CallbackNotAllowedError(AppError):
    """返送先が許されない。"""


class GlossaryPresetNotFoundError(AppError):
    """API の開始かブラウザの音声の受け付けで指定した用語集のプリセットが一覧に無い（メッセージに指定した名前を含める）。"""


class UnauthorizedError(AppError):
    """トークンが合わない。"""


class ForbiddenRequestError(AppError):
    """Origin が付いている・Host が違う。"""


class SessionNotFoundError(AppError):
    """セッションが無い・操作できない状態。"""


class SessionBusyError(AppError):
    """ほかのセッションが処理中。"""


class SessionConflictError(AppError):
    """セッションの種類がその操作を受けない（連続録音への停止）。"""


class MicrophoneUnavailableError(AppError):
    """マイクを開けない。"""


class WebJobNotFoundError(AppError):
    """ブラウザの音声のジョブが無い（受け付けていない・件数を超えて捨てた・起動し直した）。"""


class RequestBodyTooLargeError(AppError):
    """ブラウザの本文が上限以上。"""


class AudioUnreadableError(AppError):
    """受けた音声を PyAV で開けないか、音声のストリームが無い。"""


class WebQueueFullError(AppError):
    """終わっていないブラウザの音声のジョブが上限に達している。"""


class TranscriptionError(AppError):
    """文字起こしに失敗した。"""


class EngineError(AppError):
    """エンジンが失敗した。"""


class DeliveryError(AppError):
    """出力先へ届けられない。"""


class UnknownOutputError(DeliveryError):
    """選んだ出力先が一覧に無いかオフ。"""


class VolumeControlError(AppError):
    """システム音量を操作できない。"""


class SettingsError(AppError):
    """設定の値が合わない。読めなかったファイルのパスを paths に持つ。"""

    def __init__(self, *args: object, paths: tuple[Path, ...] = ()) -> None:
        super().__init__(*args)
        self.paths = paths


class StartupError(AppError):
    """起動に失敗した。"""


class HotkeyError(AppError):
    """ホットキーの書式を pynput が読めない。"""


class GlossaryReadError(AppError):
    """用語集の CSV を読めない（開けない・UTF-8 でない・見出しの列が無い・csv が解釈できない）。メッセージが設定画面に出す理由になる。"""
