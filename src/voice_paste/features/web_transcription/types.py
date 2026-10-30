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

type CorrectFn = Callable[[str, str | None], str]
"""起こした文字と用語集のプリセットの名前（None は補正の時点で設定で選んでいるプリセット）を受け、そのプリセットの用語集と文頭・文末の文言で補正して返す。設定から消えた名前は設定で選んでいるプリセットで補正する。"""

type AppendTextFn = Callable[[Path, str], None]
"""音声のパスと起こした文字を受け、同じ名前の .txt に書く（一時のファイルなら何もしない）。"""

type DiscardTemporaryFn = Callable[[Path], None]
"""音声のパスを受け、一時のファイル（`tmp/` の下）なら削除する。"""

type ProbeAudioFn = Callable[[BinaryIO], AudioProbe]
"""音声のファイルを受け、容れ物の形式・秒数・大きさを返す。開けない・音声が無いときは AudioUnreadableError。"""

type GlossaryPresetExistsFn = Callable[[str], bool]
"""用語集のプリセットの名前を受け、今の設定の一覧にあるかを返す（大文字と小文字を区別する）。"""

type ListGlossaryPresetsFn = Callable[[], GlossaryPresetChoices]
"""引数を受けず、呼んだ時点の設定の用語集のプリセットの名前の一覧と、設定で選んでいるプリセットの名前を返す。"""


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

    glossary_preset: str | None = None
    """受け付けの時点で指定された用語集のプリセットの名前。None は指定なし（補正の時点で設定で選んでいるプリセットを使う）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class GlossaryPresetChoices:
    """画面の選択欄に並べる用語集のプリセットの名前の一覧と、設定で選んでいるプリセットの名前。"""

    presets: list[str]
    """用語集のプリセットの名前の一覧（設定の並びのまま。1 件以上）。"""

    active: str
    """設定で選んでいるプリセットの名前（presets のどれか）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebTranscriptionDeps:
    """WebJobQueue が呼ぶほかの feature・外部連携の関数（main.py が部分適用して渡す）。"""

    store_audio: StoreWebAudioFn
    """受けた音声を履歴へ移す（残さない設定なら一時のファイルのまま）。"""

    transcribe: TranscribeFn
    """音声を起こす（セッションと同じ文字起こしワーカーを、今のロックで順番に使う）。"""

    correct: CorrectFn
    """用語集のプリセットの名前（None は設定で選んでいるプリセット）の用語集と、文頭・文末の文言で補正する。"""

    append_text: AppendTextFn
    """履歴の音声と同じ名前の .txt に書く。"""

    discard_temporary: DiscardTemporaryFn
    """一時のファイルなら削除する。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebApiDeps:
    """route が使う WebJobQueue と受け付けの関数（app.state.web_api に置く）。"""

    queue: WebJobQueue
    """ジョブの一覧とワーカースレッド。"""

    probe_audio: ProbeAudioFn
    """受けた音声を PyAV で開いて形式と秒数を読む。"""

    tmp_dir: Path
    """受けた音声を書く一時のフォルダ（`{AppPaths.tmp_dir}/web`）。"""

    glossary_preset_exists: GlossaryPresetExistsFn
    """指定された用語集のプリセットの名前が今の設定の一覧にあるか。"""

    list_glossary_presets: ListGlossaryPresetsFn
    """今の設定の用語集のプリセットの名前の一覧と、設定で選んでいるプリセットの名前を返す。"""

    reports_progress: bool
    """設定の文字起こしのエンジンが、起こしている途中の進みを返すか（起動時の transcription.engine が local_whisper か）。"""
