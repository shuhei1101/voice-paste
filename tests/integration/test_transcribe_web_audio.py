"""ブラウザの音声を文字に起こす（ワーカースレッド）の結合テスト。

本物の app とブラウザの音声のキュー（ワーカースレッドつき）を立て、音声を受け付けさせてから、起こす流れを確かめる。
文字起こしのエンジンは偽物、履歴は一時フォルダに書く。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import Stack, make_audio, wait_until
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import GlossaryPresetSettings
from voice_paste.shared.types import GlossaryEntry

HISTORY_DATE = "20261001"
"""偽の時計（2026-10-01 12:00）の日付のフォルダ。"""


def _job_id_of(audio_path: Path) -> str:
    """履歴に移した音声のパス（`{日時}_web_{job_id}{拡張子}`）から job_id を取り出す。"""
    return audio_path.stem.split("_web_", 1)[1]


def _history_files(stack: Stack) -> list[Path]:
    """履歴に残ったファイルを返す。"""
    return sorted(path for path in stack.paths.history_dir.rglob("*") if path.is_file())


def test_normal(stack: Stack, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """ジョブを 1 件起こし、補正した文字を履歴とジョブに残す（正常系）。"""
    # 準備: 文字を 2 区間にして区間ごとに進みを返し、起こしている間のジョブの進みを控える
    caplog.set_level(logging.INFO)
    stack.engine.segments = ["今日は晴れ", "です"]
    stack.web.glossary = [GlossaryEntry(wrong="晴れ", right="快晴")]
    progress_seen: list[float] = []

    def hook(audio_path: Path, on_progress: Callable[[float, float], None]) -> None:
        on_progress(5.0, 10.0)
        progress_seen.append(stack.web_queue.get(_job_id_of(audio_path)).progress)

    stack.engine.hook = hook
    job_id = stack.submit_audio(make_audio("webm", tmp_path))

    # 実行
    assert stack.wait_for_job(job_id, "done")

    # 検証
    body = stack.get_job(job_id).json()
    assert body["progress"] == 1.0
    assert body["text"] == "今日は快晴\nです"
    assert progress_seen == [pytest.approx(0.5)]
    audio_files = [path for path in _history_files(stack) if path.suffix == ".webm"]
    assert len(audio_files) == 1
    assert audio_files[0].parent.name == HISTORY_DATE
    assert audio_files[0].with_suffix(".txt").read_text(encoding="utf-8") == "今日は快晴\nです"
    assert list(stack.web_tmp_dir.iterdir()) == []
    assert any(job_id in line and "起こし終えた" in line for line in caplog.text.splitlines())
    assert "今日は快晴" not in caplog.text
    stack.notify.assert_not_called()


def test_normal_when_history_disabled(stack: Stack, tmp_path: Path) -> None:
    """履歴を残さない設定では、起こし終えた後に一時のファイルを削除する（正常系）。"""
    # 準備
    stack.web.history_enabled = False
    stack.engine.segments = ["決めた文"]
    job_id = stack.submit_audio(make_audio("mp4", tmp_path), filename="recording.mp4")

    # 実行
    assert stack.wait_for_job(job_id, "done")

    # 検証
    assert stack.get_job(job_id).json()["text"] == "決めた文"
    assert _history_files(stack) == []
    assert wait_until(lambda: list(stack.web_tmp_dir.iterdir()) == [])


def test_normal_when_queued_in_order(stack: Stack, tmp_path: Path) -> None:
    """積んだ順に 1 件ずつ起こし、後のジョブは queued のまま待つ（正常系）。"""
    # 準備: エンジンをテストが放すまで戻らない関数にして、2 件積む
    started: list[str] = []

    def hook(audio_path: Path, on_progress: Callable[[float, float], None]) -> None:
        started.append(_job_id_of(audio_path))
        stack.engine.release.wait(timeout=5.0)

    stack.engine.hook = hook
    audio = make_audio("webm", tmp_path)
    first_id = stack.submit_audio(audio)
    assert wait_until(lambda: len(started) == 1)
    second_id = stack.submit_audio(audio)

    # 実行: 1 件目を起こしている間の 2 件目の状態を見てから放す
    waiting_state = stack.get_job(second_id).json()["state"]
    stack.engine.release.set()

    # 検証
    assert waiting_state == "queued"
    assert stack.wait_for_job(first_id, "done")
    assert stack.wait_for_job(second_id, "done")
    assert started == [first_id, second_id]


def test_error_when_transcription_failed(stack: Stack, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """文字起こしワーカーがエラーを返したジョブを failed にして、次のジョブへ進む（異常系）。"""
    # 準備: 1 回目はエラー、2 回目は決めた文を返す
    caplog.set_level(logging.INFO)
    stack.engine.error_on_calls = {1}
    stack.engine.segments = ["二件目の文"]
    audio = make_audio("webm", tmp_path)
    first_id = stack.submit_audio(audio)
    assert stack.wait_for_job(first_id, "failed")

    # 実行
    second_id = stack.submit_audio(audio)
    assert stack.wait_for_job(second_id, "done")

    # 検証
    first = stack.get_job(first_id).json()
    assert "文字起こしに失敗した" in first["error"]
    assert first["text"] is None
    assert stack.get_job(second_id).json()["text"] == "二件目の文"
    history_audio = [path for path in _history_files(stack) if path.suffix == ".webm"]
    assert first_id in [_job_id_of(path) for path in history_audio]
    assert any(first_id in line and "失敗" in line for line in caplog.text.splitlines())
    stack.notify.assert_not_called()


def test_normal_when_glossary_preset(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """ジョブが持つ用語集のプリセットで補正する（正常系）。"""
    # 準備: 設定に「既定」と「会議」があり、設定で選んでいるのは「既定」。同じ言葉を別の言葉へ置き換える
    settings = SETTINGS_MODEL(
        glossary_presets=[
            GlossaryPresetSettings(name="既定", glossaries=[]),
            GlossaryPresetSettings(name="会議", glossaries=[]),
        ],
        active_glossary_preset="既定",
    )
    stack = web_stack(settings=settings)
    stack.engine.segments = ["今日は晴れ"]
    stack.web.preset_glossaries = {
        "既定": [GlossaryEntry(wrong="晴れ", right="既定の晴れ")],
        "会議": [GlossaryEntry(wrong="晴れ", right="会議の晴れ")],
    }
    audio = make_audio("webm", tmp_path)

    # 実行: 「会議」のジョブと、プリセットが空のジョブを 1 件ずつ積む
    meeting_id = stack.submit_audio(audio, glossary_preset="会議")
    assert stack.wait_for_job(meeting_id, "done")
    default_id = stack.submit_audio(audio)
    assert stack.wait_for_job(default_id, "done")

    # 検証
    assert stack.get_job(meeting_id).json()["text"] == "今日は会議の晴れ"
    assert stack.get_job(default_id).json()["text"] == "今日は既定の晴れ"
    assert stack.web.settings.active_glossary_preset == "既定"
