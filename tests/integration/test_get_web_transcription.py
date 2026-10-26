"""文字起こしの結果を返す（GET /web/transcriptions/{job_id}）の結合テスト。

本物の app とブラウザの音声のキュー（ワーカースレッドつき）を 127.0.0.1 の空きポートに立て、httpx で叩く。
文字起こしのエンジンは偽物で、ジョブの状態はエンジンの動きで作る。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import Stack, make_audio, wait_until
from voice_paste.shared.errors import EngineError
from voice_paste.shared.types import GlossaryEntry

JOB_ID_LENGTH = 22


def test_normal(stack: Stack, tmp_path: Path) -> None:
    """文字起こしが終わったジョブの、補正した文字を返す（正常系）。"""
    # 準備
    stack.engine.segments = ["補正前の文"]
    stack.web.glossary = [GlossaryEntry(wrong="補正前", right="補正後")]
    job_id = stack.submit_audio(make_audio("webm", tmp_path))
    assert stack.wait_for_job(job_id, "done")

    # 実行
    first = stack.get_job(job_id)
    second = stack.get_job(job_id)

    # 検証
    expected = {
        "job_id": job_id,
        "state": "done",
        "progress": 1.0,
        "text": "補正後の文",
        "error": None,
    }
    assert first.status_code == 200
    assert first.json() == expected
    assert second.json() == expected


def test_normal_when_in_progress(stack: Stack, tmp_path: Path) -> None:
    """文字起こし待ち・文字起こし中のジョブの進み具合を返す（正常系）。"""
    # 準備: 1 件目は進み 0.42 を知らせたところで止め、2 件目は待たせる
    reported = {"count": 0}

    def hook(audio_path: Path, on_progress: Callable[[float, float], None]) -> None:
        on_progress(4.2, 10.0)
        reported["count"] += 1
        stack.engine.release.wait(timeout=5.0)

    stack.engine.hook = hook
    audio = make_audio("webm", tmp_path)
    running_id = stack.submit_audio(audio)
    assert wait_until(lambda: reported["count"] == 1)
    queued_id = stack.submit_audio(audio)

    # 実行
    running = stack.get_job(running_id).json()
    queued = stack.get_job(queued_id).json()

    # 検証
    assert (running["state"], running["progress"], running["text"], running["error"]) == (
        "running",
        pytest.approx(0.42),
        None,
        None,
    )
    assert (queued["state"], queued["progress"], queued["text"], queued["error"]) == (
        "queued",
        0.0,
        None,
        None,
    )


def test_normal_when_failed(stack: Stack, tmp_path: Path) -> None:
    """文字起こしに失敗したジョブの理由を返す（正常系）。"""
    # 準備
    stack.engine.error = EngineError("文字起こしワーカー無応答")
    job_id = stack.submit_audio(make_audio("webm", tmp_path))
    assert stack.wait_for_job(job_id, "failed")

    # 実行
    response = stack.get_job(job_id)

    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["state"] == "failed"
    assert "文字起こしワーカー無応答" in body["error"]
    assert body["text"] is None


def test_error_when_origin_not_allowed(stack: Stack, tmp_path: Path) -> None:
    """許す Origin に無い Origin が付いた要求を断る（異常系）。"""
    # 準備
    stack.engine.segments = ["起こした文字"]
    job_id = stack.submit_audio(make_audio("webm", tmp_path))
    assert stack.wait_for_job(job_id, "done")

    # 実行
    response = stack.get_job(job_id, headers={"Origin": "http://evil.example"})

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "起こした文字" not in response.text


def test_error_when_job_not_found(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """受け付けていない job_id と、件数を超えて捨てたジョブを 404 にする（異常系）。"""
    # 準備: 終わったジョブを持つ件数を 1 件にし、2 件を終わらせる
    stack = web_stack(max_finished=1)
    audio = make_audio("webm", tmp_path)
    first_id = stack.submit_audio(audio)
    assert stack.wait_for_job(first_id, "done")
    second_id = stack.submit_audio(audio)
    assert stack.wait_for_job(second_id, "done")

    # 実行
    missing = stack.get_job("q3Vb8sXk2mJf0tLw9eRzAg")
    discarded = stack.get_job(first_id)
    kept = stack.get_job(second_id)

    # 検証
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert discarded.status_code == 404
    assert kept.status_code == 200
    assert kept.json()["state"] == "done"
