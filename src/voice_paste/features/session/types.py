"""セッションの状態・セッション・ほかの feature を受け取る関数型。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from voice_paste.shared.settings import Preset
from voice_paste.shared.types import (
    Entry,
    OnContinuousFailedFn,
    OnSegmentFn,
    ProgressFn,
    Recording,
    TranscriptionOutcome,
)

if TYPE_CHECKING:
    from voice_paste.features.session.service import SessionManager


class SessionState(StrEnum):
    """セッションがどこまで進んだか。"""

    RECORDING = "recording"
    """マイクで録音している（連続録音では、区切った区間を起こして返しながら録音を続けている）。"""

    PAUSED = "paused"
    """ホットキー・トレイから始めた録音を一時停止している（再開できる）。"""

    STOPPED = "stopped"
    """API から始めた録音を止め、完了を待っている。"""

    TRANSCRIBING = "transcribing"
    """確定した録音を文字に起こしている（連続録音では、完了か上限の後に残りの区間と終わりを返している）。"""

    DELIVERING = "delivering"
    """出力先へ届けている。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    """動いている 1 回分の流れ。"""

    id: str
    """セッションの ID（uuid4）。"""

    entry: Entry
    """始めた入口。"""

    state: SessionState
    """今の状態。"""

    started_at: datetime
    """始めた時刻。API のセッションの上限時間をここから数える。"""

    callback_url: str | None
    """API から始めたときの返送先。それ以外は None。"""

    output_id: str | None
    """ホットキー・トレイから始めた録音で、確定の操作で選んだ出力先の ID。"""

    output_preset: Preset | None
    """ホットキー・トレイから始めた録音で、確定の操作で選んだカスタムプリセット（確定したときの設定の写し）。固定の出力先を選んだときと API のときは None。"""

    recording: Recording | None = None
    """API の録音を止めた後、完了までセッションが持つ貯めた音。"""

    continuous: bool = False
    """API の連続録音か。"""

    segment_count: int = 0
    """連続録音でこれまでに区切った区間の数（最後に付けた通し番号）。"""


type StartRecordingFn = Callable[[], None]
"""音量を下げてマイクを開く。開けなければ音量を戻して MicrophoneUnavailableError を送出する。"""

type StopRecordingFn = Callable[[], Recording]
"""録音を止めて音量を戻し、貯めた音を返す。"""

type SaveRecordingFn = Callable[[str, Recording, int | None], Path]
"""セッションの ID と確定した録音（連続録音では区間の音）と区間の通し番号（連続録音でなければ None）を受け、履歴（残さない設定なら一時の音声）へ書いたパスを返す。"""

type StartContinuousRecordingFn = Callable[[OnSegmentFn, OnContinuousFailedFn], None]
"""区間の渡し先と区切りの失敗の知らせ先を受け、音量を下げてマイクを開き、区切った区間を区切った順に渡す。開けなければ音量を戻して MicrophoneUnavailableError を送出する。"""

type TranscribeFn = Callable[[Path, ProgressFn | None], str]
"""録音のファイルと進みを知らせる関数を受け、起こした文字を返す。失敗は TranscriptionError。"""

type AppendTextFn = Callable[[Path, str], None]
"""保存した録音のパスと起こした文字を受け、録音と同じ履歴に書き足す。"""

type DeliverFn = Callable[[Session, TranscriptionOutcome], None]
"""届けるセッションと結果を受け、出力先へ届ける。API のセッションは呼び出し元へ返す出力先だけを使う。"""

type NotifyFn = Callable[
    [
        Literal[
            "state_changed",
            "busy",
            "microphone_unavailable",
            "transcription_failed",
            "delivery_failed",
            "api_unavailable",
            "output_changed",
        ],
        str | None,
    ],
    None,
]
"""知らせの種類と理由の文字を受け、状態の変化と失敗を画面・トレイへ渡す。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionDeps:
    """ほかの feature と入口を関数型で束ねたもの。main.py で配線する。"""

    start_recording: StartRecordingFn
    """録音を始める（音量を下げ、マイクを開く）。"""

    pause_recording: Callable[[], None]
    """録音した音を貯めるのを止める。"""

    resume_recording: Callable[[], None]
    """録音した音を貯めるのを再び始める。"""

    stop_recording: StopRecordingFn
    """録音を止めて音量を戻し、録音を返す。"""

    discard_recording: Callable[[], None]
    """録音を止めて音量を戻し、貯めた音を捨てる。"""

    save_recording: SaveRecordingFn
    """確定した録音を履歴か一時の音声へ保存する。"""

    transcribe: TranscribeFn
    """録音を文字に起こす（失敗は TranscriptionError）。"""

    correct: Callable[[str], str]
    """用語集で補正する。"""

    append_text: AppendTextFn
    """起こした文字を履歴に書き足す。"""

    deliver: DeliverFn
    """結果を出力先へ届ける。"""

    notify: NotifyFn
    """ユーザーへ知らせる（画面・トレイ。メインスレッドへは Signal で渡す）。"""

    now: Callable[[], datetime]
    """今の時刻（テストで差し替える）。"""

    discard_temporary: Callable[[Path], None]
    """処理を終えた録音が一時の音声なら消す（履歴の discard_temporary）。"""

    report_progress: ProgressFn
    """ホットキー・トレイの録音で、文字起こしの進みを画面へ知らせる（配線では ui の report_progress）。"""

    start_continuous_recording: StartContinuousRecordingFn
    """連続録音を始める（音量を下げ、マイクを開き、区切った区間を渡し先へ渡す）。"""

    stop_continuous_recording: Callable[[], None]
    """連続録音を止めて音量を戻し、区間に切り出していない話し声を最後の区間として渡し終えてから戻る。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionApiDeps:
    """route が使う配線済みのもの。main.py で組み、build_fastapi が app.state.session_api に置く。"""

    session_manager: SessionManager
    """セッション管理。"""

    is_callback_allowed: Callable[[str], bool]
    """設定の許可ホストを部分適用した返送先の確かめ（出力先の is_callback_allowed）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuousEnd:
    """連続録音の区間の待ち行列へ、全ての区間の後ろに積む終わりの印。"""

    result: Literal["completed", "truncated", "failed"]
    """完了・上限での打ち切り・区切りの失敗のどれで終えたか。"""

    error: str | None = None
    """failed のときの理由。"""
