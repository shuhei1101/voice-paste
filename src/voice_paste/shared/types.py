"""feature の間を渡る型。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

import numpy as np

type ProgressFn = Callable[[float, float], None]
"""文字起こしの区間の終わりの時刻と録音の長さ（秒）を知らせる関数。"""

type EnterModifier = Literal["ctrl", "alt", "shift"]
"""貼り付けて送信が Enter と一緒に押す修飾キー。出力先の設定と integrations/keyboard が使う。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioProbe:
    """受けた音声を PyAV で開いて読んだ容れ物の形式・秒数・大きさ。"""

    container: str
    """容れ物の形式の名前（`matroska,webm`・`ogg`・`mov,mp4,m4a,3gp,3g2,mj2`・`mp3`・`wav` など）。"""

    suffix: str
    """一時のファイルと履歴に付ける拡張子（`.webm` など。container から決める）。"""

    duration_sec: float | None
    """音声の秒数。容れ物が持たず、パケットからも求まらないときは None。"""

    size_bytes: int
    """音声の大きさ。"""


class SendEnterFn(Protocol):
    """渡した修飾キーを押したまま Enter を送る関数。修飾キーを省くと Enter だけを送る。"""

    def __call__(self, modifiers: Sequence[EnterModifier] = ()) -> None:
        """修飾キーを押したまま Enter を送る。"""
        ...


class Entry(StrEnum):
    """セッションを始めた入口。"""

    HOTKEY = "hotkey"
    """録音開始のホットキー。"""

    TRAY = "tray"
    """トレイのメニュー。"""

    API = "api"
    """POST /sessions。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class TranscriptionOutcome:
    """出力先へ渡す文字起こしの結果。"""

    session_id: str
    """セッションの ID。"""

    result: Literal["transcribed", "failed", "truncated", "completed"]
    """結果の種類。completed は連続録音を完了し、全ての区間を届け終えたときだけ。"""

    text: str
    """用語集で補正した文字。空・失敗・打ち切り・完了は空文字。"""

    error: str | None
    """失敗の理由。"""

    segment_number: int | None = None
    """連続録音の区間の通し番号（1 始まり）。連続録音の transcribed・failed だけが持つ。"""

    segment_count: int | None = None
    """連続録音で区切った区間の数。連続録音の終わり（completed・truncated、区切りに失敗して止めたときの failed）だけが持つ。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class GlossaryEntry:
    """用語集の行（誤変換と正しい表記の組と、補正に使うか）。補正と設定画面の間を渡る。"""

    wrong: str
    """誤変換（CSV の列 `誤変換`）。"""

    right: str
    """正しい表記（CSV の列 `正しい表記`）。"""

    enabled: bool = True
    """補正に使うか（CSV の列 `使う`。`0` がオフ）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Recording:
    """止めた録音の音と形式。"""

    samples: np.ndarray
    """モノラルの 16 bit の音。"""

    sample_rate: int
    """サンプルレート（Hz）。"""

    duration_sec: float
    """録音の長さ（一時停止の間を除く）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Segment:
    """連続録音で区切った 1 区間の音。録音が作り、セッションが受ける。"""

    recording: Recording
    """区間の音（16 kHz・モノラル・int16）。"""

    reason: Literal["silence", "max_length", "flush"]
    """区切った理由。silence: 話し声の後の無音、max_length: 区間の最大の長さ、flush: 録音を止めたときの残り。"""


type OnSegmentFn = Callable[[Segment], None]
"""区切った区間を区切った順に受け取る関数。録音の区切りのスレッドから呼ばれる。"""

type OnContinuousFailedFn = Callable[[str], None]
"""区切りに失敗して連続録音を止めたことを、理由を添えて受け取る関数。録音の区切りのスレッドから呼ばれる。"""
