"""ジョブの状態・ジョブ・ほかの feature を受け取る関数型・API の依存。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from voice_paste.shared.types import AudioProbe, ProgressFn

if TYPE_CHECKING:
    from voice_paste.features.web_transcription.service import WebJobQueue

type StoreWebAudioFn = Callable[[str, Path], Path]
"""ジョブの ID と一時のファイルを受け、履歴を残す設定なら履歴へ移してそのパスを、残さない設定なら一時のファイルのままそのパスを返す。"""

type TranscribeFn = Callable[[Path, ProgressFn], str]
"""音声のファイルと進みを知らせる関数を受け、起こした文字を返す。失敗は TranscriptionError。"""

type CorrectFn = Callable[[str], str]
"""起こした文字を、今の設定の用語集と文頭・文末の文言で補正して返す。"""

type AppendTextFn = Callable[[Path, str], None]
"""音声のパスと起こした文字を受け、同じ名前の .txt に書く（一時のファイルなら何もしない）。"""

type DiscardTemporaryFn = Callable[[Path], None]
"""音声のパスを受け、一時のファイル（`tmp/` の下）なら消す。"""

type ProbeAudioFn = Callable[[BinaryIO], AudioProbe]
"""音声のファイルを受け、容れ物の形式・秒数・大きさを返す。開けない・音声が無いときは AudioUnreadableError。"""


class JobState(StrEnum):
    """ジョブがどこまで進んだか。値は API の `state` にそのまま出る。"""

    QUEUED = "queued"
    """受け付けてキューに積んだ（文字起こし待ち）。"""

    RUNNING = "running"
    """ワーカースレッドが起こしている（文字起こし中）。"""

    DONE = "done"
    """起こして補正した文字を持つ（文字起こし完了）。"""

    FAILED = "failed"
    """文字起こしに失敗した理由を持つ（文字起こし失敗）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebJob:
    """ブラウザから受けた音声 1 件分の状態と結果。状態が変わるたびに WebJobQueue が `replace` で差し替える。"""

    id: str
    """ジョブの ID（`secrets.token_urlsafe(16)`、22 文字）。"""

    state: JobState
    """今の状態。"""

    audio_path: Path
    """受けた音声の一時のファイル（`tmp/web/{id}{拡張子}`）。履歴へ移した後は履歴のパス。"""

    audio: AudioProbe
    """受け付けで読んだ容れ物の形式・秒数・大きさ。"""

    progress: float = 0.0
    """進み具合（0.0〜1.0）。"""

    text: str | None = None
    """done のときの補正した文字。"""

    error: str | None = None
    """failed のときの失敗の理由。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebTranscriptionDeps:
    """WebJobQueue が呼ぶほかの feature・外部連携の関数（main.py が部分適用して渡す）。"""

    store_audio: StoreWebAudioFn
    """受けた音声を履歴へ移す（残さない設定なら一時のファイルのまま）。"""

    transcribe: TranscribeFn
    """音声を起こす（セッションと同じ文字起こしワーカーを、今のロックで順番に使う）。"""

    correct: CorrectFn
    """用語集と文頭・文末の文言で補正する。"""

    append_text: AppendTextFn
    """履歴の音声と同じ名前の .txt に書く。"""

    discard_temporary: DiscardTemporaryFn
    """一時のファイルなら消す。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebApiDeps:
    """route が使う WebJobQueue と受け付けの関数（app.state.web_api に置く）。"""

    queue: WebJobQueue
    """ジョブの一覧とワーカースレッド。"""

    probe_audio: ProbeAudioFn
    """受けた音声を PyAV で開いて形式と秒数を読む。"""

    tmp_dir: Path
    """受けた音声を書く一時のフォルダ（`{AppPaths.tmp_dir}/web`）。"""
