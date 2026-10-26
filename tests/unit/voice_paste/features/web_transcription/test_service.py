"""features/web_transcription/service.py（WebJobQueue・accept_audio）の単体テスト。

ほかの feature・外部連携の関数（WebTranscriptionDeps）は Mock にする。
ワーカースレッドを立てないテストは、_process を直接呼んで 1 件ずつ進める。
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest

if TYPE_CHECKING:
    from voice_paste.features.web_transcription.service import WebJobQueue
    from voice_paste.features.web_transcription.types import (
        WebApiDeps,
        WebJob,
        WebTranscriptionDeps,
    )
    from voice_paste.shared.types import AudioProbe

TRANSCRIBED = "起こした文字"
"""transcribe が返す文字。"""

WAIT_SEC = 5.0
"""ワーカースレッドの完了を待つ上限。"""

POLL_SEC = 0.01
"""ワーカースレッドの完了を確かめる間隔。"""


def _audio() -> AudioProbe:
    """受け付けで読んだ形式（webm・10 秒）を返す。"""
    from voice_paste.shared.types import AudioProbe

    return AudioProbe(container="webm", suffix=".webm", duration_sec=10.0, size_bytes=4096)


def _make_deps(
    *,
    transcribe: Callable[..., str] | None = None,
    correct: Callable[[str, str | None], str] | None = None,
) -> WebTranscriptionDeps:
    """呼び出しを覚える Mock の WebTranscriptionDeps を作る。transcribe・correct は差し替えられる。"""
    from voice_paste.features.web_transcription.types import WebTranscriptionDeps

    return WebTranscriptionDeps(
        store_audio=MagicMock(side_effect=lambda job_id, source: source),
        transcribe=MagicMock(side_effect=transcribe or (lambda audio_path, on_progress: TRANSCRIBED)),
        correct=MagicMock(side_effect=correct or (lambda text, glossary_preset: f"補正:{text}")),
        append_text=MagicMock(),
        discard_temporary=MagicMock(),
    )


def _make_queue(deps: WebTranscriptionDeps, **limits: int) -> WebJobQueue:
    """ワーカースレッドを立てない WebJobQueue を作る。limits は max_pending・max_finished。"""
    from voice_paste.features.web_transcription.service import WebJobQueue

    return WebJobQueue(deps, **limits)


def _touch(path: Path) -> Path:
    """親のフォルダごと空のファイルを作ってそのパスを返す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _wait_until(condition: Callable[[], bool]) -> bool:
    """condition が真になるまで WAIT_SEC を上限に待ち、真になったかを返す。"""
    deadline = time.monotonic() + WAIT_SEC
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(POLL_SEC)
    return False


# === WebJobQueue ===


def test_start(tmp_path: Path) -> None:
    """取り残しを削除してスレッドを立てる（正常系）。"""
    from voice_paste.features.web_transcription.types import JobState

    # 準備: tmp_dir に前の起動の取り残し（.webm）がある
    tmp_dir = tmp_path / "web"
    stale = _touch(tmp_dir / "stale.webm")
    queue = _make_queue(_make_deps())

    # 実行: 立ててから音声を積む
    queue.start(tmp_dir)
    queue.submit("job1", tmp_dir / "job1.webm", _audio(), glossary_preset=None)
    finished = _wait_until(lambda: queue.get("job1").state == JobState.DONE)
    queue.close()

    # 検証: 取り残しが消え、ワーカースレッドが積んだジョブを起こして終えた
    assert not stale.exists()
    assert finished


def test_submit() -> None:
    """queued で積む（正常系）。"""
    from voice_paste.features.web_transcription.types import JobState

    # 準備
    queue = _make_queue(_make_deps())

    # 実行: プリセット「会議」を持たせた 1 件と、指定なしの 1 件
    with_preset = queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset="会議")
    without_preset = queue.submit("job2", Path("job2.webm"), _audio(), glossary_preset=None)

    # 検証
    assert with_preset.id == "job1"
    assert with_preset.state == JobState.QUEUED
    assert with_preset.glossary_preset == "会議"
    assert queue.get("job1") == with_preset
    assert without_preset.id == "job2"
    assert without_preset.state == JobState.QUEUED
    assert without_preset.glossary_preset is None
    assert queue.get("job2") == without_preset


def test_submit_when_queue_full() -> None:
    """上限で断る（異常系）。"""
    from voice_paste.shared.errors import WebJobNotFoundError, WebQueueFullError

    # 準備: 終わっていないジョブの上限が 2 件で、2 件積んである
    queue = _make_queue(_make_deps(), max_pending=2)
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset=None)
    queue.submit("job2", Path("job2.webm"), _audio(), glossary_preset=None)

    # 実行・検証
    with pytest.raises(WebQueueFullError):
        queue.submit("job3", Path("job3.webm"), _audio(), glossary_preset=None)
    assert queue.get("job1").id == "job1"
    assert queue.get("job2").id == "job2"
    with pytest.raises(WebJobNotFoundError):
        queue.get("job3")


def test_get_when_not_found() -> None:
    """無い ID は断る（異常系）。"""
    from voice_paste.shared.errors import WebJobNotFoundError

    # 準備
    queue = _make_queue(_make_deps())

    # 実行・検証
    with pytest.raises(WebJobNotFoundError):
        queue.get("missing")


def test_process() -> None:
    """起こして補正し、done で終える（正常系）。"""
    from voice_paste.features.web_transcription.types import JobState

    # 準備: transcribe は進み 0.5 を知らせ、その途中のジョブの状態を控えてから文を返す
    seen: list[WebJob] = []

    def transcribe(audio_path: Path, on_progress: Callable[[float, float], None]) -> str:
        on_progress(5.0, 10.0)
        seen.append(queue.get("job1"))
        return TRANSCRIBED

    deps = _make_deps(transcribe=transcribe)
    queue = _make_queue(deps)
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset=None)

    # 実行
    queue._process("job1")  # noqa: SLF001 ワーカースレッドの本体の 1 件分を直接呼ぶ

    # 検証
    job = queue.get("job1")
    assert job.state == JobState.DONE
    assert job.progress == 1.0
    assert job.text == f"補正:{TRANSCRIBED}"
    assert job.error is None
    assert deps.correct.call_args_list == [call(TRANSCRIBED, None)]
    assert deps.store_audio.call_count == 1
    assert deps.append_text.call_count == 1
    assert deps.discard_temporary.call_count == 1
    assert seen[0].state == JobState.RUNNING
    assert seen[0].progress == pytest.approx(0.5)


def test_process_when_transcription_failed() -> None:
    """失敗は failed で終えて次へ進む（異常系）。"""
    from voice_paste.features.web_transcription.types import JobState
    from voice_paste.shared.errors import TranscriptionError

    # 準備
    def transcribe(audio_path: Path, on_progress: Callable[[float, float], None]) -> str:
        raise TranscriptionError("文字起こしワーカー無応答")

    deps = _make_deps(transcribe=transcribe)
    queue = _make_queue(deps)
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset=None)

    # 実行
    queue._process("job1")  # noqa: SLF001 ワーカースレッドの本体の 1 件分を直接呼ぶ

    # 検証
    job = queue.get("job1")
    assert job.state == JobState.FAILED
    assert job.error is not None
    assert "文字起こしワーカー無応答" in job.error
    assert job.text is None
    assert deps.discard_temporary.call_count == 1
    assert deps.append_text.call_count == 0


def test_process_when_unexpected_error() -> None:
    """想定していない例外も failed で終える（異常系）。"""
    from voice_paste.features.web_transcription.types import JobState

    # 準備: correct が ValueError を送出する
    def correct(text: str, glossary_preset: str | None) -> str:
        raise ValueError("内部の詳細")

    queue = _make_queue(_make_deps(correct=correct))
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset=None)

    # 実行
    queue._process("job1")  # noqa: SLF001 ワーカースレッドの本体の 1 件分を直接呼ぶ

    # 検証
    job = queue.get("job1")
    assert job.state == JobState.FAILED
    assert job.error is not None
    assert "内部の詳細" not in job.error


def test_process_when_over_finished_limit() -> None:
    """終わったジョブは件数で古い順に捨てる（正常系）。"""
    from voice_paste.features.web_transcription.types import JobState
    from voice_paste.shared.errors import WebJobNotFoundError

    # 準備: 終わったジョブを持つ件数が 1 件で、2 件を終える
    queue = _make_queue(_make_deps(), max_finished=1)
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset=None)
    queue.submit("job2", Path("job2.webm"), _audio(), glossary_preset=None)

    # 実行
    queue._process("job1")  # noqa: SLF001 ワーカースレッドの本体の 1 件分を直接呼ぶ
    queue._process("job2")  # noqa: SLF001 同上

    # 検証
    with pytest.raises(WebJobNotFoundError):
        queue.get("job1")
    assert queue.get("job2").state == JobState.DONE


def test_process_when_glossary_preset() -> None:
    """ジョブのプリセットで補正する（正常系）。"""
    from voice_paste.features.web_transcription.types import JobState

    # 準備: プリセット「会議」のジョブ 1 件。correct は固定の文字を返す
    deps = _make_deps(correct=lambda text, glossary_preset: "会議で補正した文字")
    queue = _make_queue(deps)
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset="会議")

    # 実行
    queue._process("job1")  # noqa: SLF001 ワーカースレッドの本体の 1 件分を直接呼ぶ

    # 検証
    job = queue.get("job1")
    assert job.state == JobState.DONE
    assert job.text == "会議で補正した文字"
    assert deps.correct.call_args_list == [call(TRANSCRIBED, "会議")]


def test_close() -> None:
    """待ちの一時のファイルを削除する（正常系）。"""
    # 準備: ワーカースレッドを立てず、queued のジョブが 2 件ある
    deps = _make_deps()
    queue = _make_queue(deps)
    queue.submit("job1", Path("job1.webm"), _audio(), glossary_preset=None)
    queue.submit("job2", Path("job2.webm"), _audio(), glossary_preset=None)

    # 実行
    queue.close()

    # 検証
    assert deps.discard_temporary.call_count == 2


# === accept_audio ===


class _SpyQueue:
    """submit の呼び出しを覚え、積んだジョブを返す（失敗させたいときは error を送出する）。"""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, Path, AudioProbe, str | None]] = []

    def submit(
        self, job_id: str, audio_path: Path, audio: AudioProbe, glossary_preset: str | None
    ) -> WebJob:
        """呼び出しを覚えて、queued のジョブを返す。"""
        from voice_paste.features.web_transcription.types import JobState, WebJob

        if self.error is not None:
            raise self.error
        self.calls.append((job_id, audio_path, audio, glossary_preset))
        return WebJob(
            id=job_id,
            state=JobState.QUEUED,
            audio_path=audio_path,
            audio=audio,
            glossary_preset=glossary_preset,
        )


def _make_api_deps(
    tmp_dir: Path,
    queue: _SpyQueue,
    probe_error: Exception | None = None,
    preset_exists: bool = True,
) -> WebApiDeps:
    """submit を覚えるキューと、webm を返す（probe_error があれば送出する）形式の読み取りと、preset_exists を返すプリセットの確かめの WebApiDeps を作る。"""
    from voice_paste.features.web_transcription.types import WebApiDeps

    tmp_dir.mkdir(parents=True, exist_ok=True)
    return WebApiDeps(
        queue=queue,  # type: ignore[arg-type] 呼ぶのは submit だけ
        probe_audio=MagicMock(return_value=_audio(), side_effect=probe_error),
        tmp_dir=tmp_dir,
        glossary_preset_exists=MagicMock(return_value=preset_exists),
        list_glossary_presets=MagicMock(),  # accept_audio は呼ばない
    )


def test_accept_audio(tmp_path: Path) -> None:
    """容れ物の拡張子で書いて積む（正常系）。"""
    from voice_paste.features.web_transcription.service import accept_audio

    # 準備
    tmp_dir = tmp_path / "web"
    queue = _SpyQueue()
    deps = _make_api_deps(tmp_dir, queue)

    # 実行
    job = accept_audio(io.BytesIO(b"webm-bytes"), deps=deps)

    # 検証
    written = list(tmp_dir.iterdir())
    assert len(written) == 1
    assert written[0].suffix == ".webm"
    assert written[0].read_bytes() == b"webm-bytes"
    assert queue.calls == [(written[0].stem, written[0], _audio(), None)]
    assert job.id == written[0].stem
    assert len(job.id) == 22


def test_accept_audio_when_unreadable(tmp_path: Path) -> None:
    """読めなければ書かない（異常系）。"""
    from voice_paste.features.web_transcription.service import accept_audio
    from voice_paste.shared.errors import AudioUnreadableError

    # 準備
    tmp_dir = tmp_path / "web"
    queue = _SpyQueue()
    deps = _make_api_deps(tmp_dir, queue, probe_error=AudioUnreadableError("読めない"))

    # 実行・検証
    with pytest.raises(AudioUnreadableError):
        accept_audio(io.BytesIO(b"not-audio"), deps=deps)
    assert list(tmp_dir.iterdir()) == []
    assert queue.calls == []


def test_accept_audio_when_queue_full(tmp_path: Path) -> None:
    """待ちが上限なら書いたファイルを削除する（異常系）。"""
    from voice_paste.features.web_transcription.service import accept_audio
    from voice_paste.shared.errors import WebQueueFullError

    # 準備
    tmp_dir = tmp_path / "web"
    queue = _SpyQueue(error=WebQueueFullError("待ちが上限"))
    deps = _make_api_deps(tmp_dir, queue)

    # 実行・検証
    with pytest.raises(WebQueueFullError):
        accept_audio(io.BytesIO(b"webm-bytes"), deps=deps)
    assert list(tmp_dir.iterdir()) == []


def test_accept_audio_when_glossary_preset(tmp_path: Path) -> None:
    """一覧にあるプリセットを持たせて積む（正常系）。"""
    from voice_paste.features.web_transcription.service import accept_audio

    # 準備: 「会議」は今の設定の一覧にある
    tmp_dir = tmp_path / "web"
    queue = _SpyQueue()
    deps = _make_api_deps(tmp_dir, queue, preset_exists=True)

    # 実行
    job = accept_audio(io.BytesIO(b"webm-bytes"), deps=deps, glossary_preset="会議")

    # 検証
    assert deps.glossary_preset_exists.call_args_list == [call("会議")]
    assert [queue_call[3] for queue_call in queue.calls] == ["会議"]
    assert job.glossary_preset == "会議"


def test_accept_audio_when_glossary_preset_empty(tmp_path: Path) -> None:
    """空文字は指定なしとして積む（正常系）。"""
    from voice_paste.features.web_transcription.service import accept_audio

    # 準備
    tmp_dir = tmp_path / "web"
    queue = _SpyQueue()
    deps = _make_api_deps(tmp_dir, queue)

    # 実行
    job = accept_audio(io.BytesIO(b"webm-bytes"), deps=deps, glossary_preset="")

    # 検証
    assert deps.glossary_preset_exists.call_count == 0
    assert [queue_call[3] for queue_call in queue.calls] == [None]
    assert job.glossary_preset is None


def test_accept_audio_when_glossary_preset_not_found(tmp_path: Path) -> None:
    """一覧に無いプリセットは音声を読まずに断る（異常系）。"""
    from voice_paste.features.web_transcription.service import accept_audio
    from voice_paste.shared.errors import GlossaryPresetNotFoundError

    # 準備: 「無いプリセット」は今の設定の一覧に無い
    tmp_dir = tmp_path / "web"
    queue = _SpyQueue()
    deps = _make_api_deps(tmp_dir, queue, preset_exists=False)

    # 実行・検証
    with pytest.raises(GlossaryPresetNotFoundError, match="無いプリセット"):
        accept_audio(io.BytesIO(b"webm-bytes"), deps=deps, glossary_preset="無いプリセット")
    assert deps.probe_audio.call_count == 0
    assert queue.calls == []
    assert list(tmp_dir.iterdir()) == []
