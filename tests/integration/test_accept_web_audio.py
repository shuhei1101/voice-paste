"""音声を受け付ける（POST /web/transcriptions）の結合テスト。

本物の app を 127.0.0.1 の空きポートに立て、httpx で叩く。ゲートウェイを通した構成（Host は localhost:{ポート}・許す Origin つき・トークン無し）で送信する。
ブラウザの音声のキューは本物で、積んだジョブを取り出さない（ワーカースレッドを立てない）構成にする。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import Stack, make_audio
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import GlossaryPresetSettings

PRESET_SETTINGS = SETTINGS_MODEL(
    glossary_presets=[
        GlossaryPresetSettings(name="既定", glossaries=[]),
        GlossaryPresetSettings(name="会議", glossaries=[]),
    ],
    active_glossary_preset="既定",
)
"""用語集のプリセット「既定」と「会議」があり、設定で選んでいるのは「既定」の設定。"""

JOB_ID_LENGTH = 22
"""ジョブの ID（secrets.token_urlsafe(16)）の文字数。"""


def _no_worker_stack(web_stack: Callable[..., Stack]) -> Stack:
    """積んだジョブを取り出さない一式を立てる。"""
    return web_stack(worker=False)


def test_normal(
    web_stack: Callable[..., Stack], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """許す Origin から送信された音声を受け付け、job_id を返す（正常系）。"""
    # 準備
    caplog.set_level(logging.INFO)
    stack = _no_worker_stack(web_stack)
    audio = make_audio("webm", tmp_path)

    # 実行
    response = stack.post_audio(audio)

    # 検証
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert len(job_id) == JOB_ID_LENGTH
    written = list(stack.web_tmp_dir.iterdir())
    assert [path.suffix for path in written] == [".webm"]
    assert written[0].read_bytes() == audio
    job = stack.get_job(job_id).json()
    assert job["state"] == "queued"
    assert job["progress"] == 0.0
    assert job_id in caplog.text
    assert str(len(audio)) in caplog.text


def test_normal_when_session_busy(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """ホットキーの録音中でも音声を受け付ける（正常系）。"""
    # 準備
    stack = _no_worker_stack(web_stack)
    stack.manager.start("hotkey")

    # 実行
    response = stack.post_audio(make_audio("webm", tmp_path))

    # 検証
    assert response.status_code == 202
    assert response.json()["job_id"]
    assert stack.state() == "recording"


def test_error_when_audio_missing(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """audio の項目が無い要求を断る（異常系）。"""
    # 準備
    stack = _no_worker_stack(web_stack)

    # 実行
    response = stack.post_audio(make_audio("webm", tmp_path), field_name="file")

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert list(stack.web_tmp_dir.iterdir()) == []


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param("http://evil.example", id="other_origin"),
        pytest.param(None, id="no_origin"),
    ],
)
def test_error_when_origin_not_allowed(
    web_stack: Callable[..., Stack],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    origin: str | None,
) -> None:
    """Origin が無いか許す Origin に無い要求を、本文を読まずに断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    stack = _no_worker_stack(web_stack)

    # 実行
    response = stack.post_audio(make_audio("webm", tmp_path), origin=origin)

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert list(stack.web_tmp_dir.iterdir()) == []
    assert f"localhost:{stack.port}" in caplog.text


@pytest.mark.parametrize("chunked", [True, False], ids=["chunked", "content_length"])
def test_error_when_too_large(
    web_stack: Callable[..., Stack], tmp_path: Path, chunked: bool
) -> None:
    """本文が上限以上の要求を断り、一時のファイルを残さない（異常系）。"""
    # 準備: 本文の上限を 1,000 バイトにし、それ以上の本文を送信する
    stack = web_stack(worker=False, body_limit=1000)
    audio = b"x" * 1500

    # 実行
    response = stack.post_audio_chunked(audio) if chunked else stack.post_audio(audio)

    # 検証
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")
    assert list(stack.web_tmp_dir.iterdir()) == []


@pytest.mark.parametrize("kind", ["text", "video_only_mp4"])
def test_error_when_unreadable_format(
    web_stack: Callable[..., Stack], tmp_path: Path, kind: str
) -> None:
    """PyAV で開けない中身と、音声のストリームの無い中身を断る（異常系）。"""
    # 準備
    stack = _no_worker_stack(web_stack)
    if kind == "text":
        data, filename = "これは音声ではありません".encode(), "notes.mp3"
    else:
        data, filename = make_audio("video_only_mp4", tmp_path), "video.mp4"

    # 実行
    response = stack.post_audio(data, filename=filename, content_type="audio/mpeg")

    # 検証
    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/problem+json")
    assert list(stack.web_tmp_dir.iterdir()) == []


def test_error_when_queue_full(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """終わっていないジョブが待ちの上限に達していれば断る（異常系）。"""
    # 準備: 待ちの上限を 2 件にし、キューから取り出さない一式に 2 件受け付けておく
    stack = web_stack(worker=False, max_pending=2)
    audio = make_audio("webm", tmp_path)
    accepted = [stack.submit_audio(audio) for _ in range(2)]

    # 実行
    response = stack.post_audio(audio)

    # 検証
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert len(list(stack.web_tmp_dir.iterdir())) == 2
    assert [stack.get_job(job_id).json()["state"] for job_id in accepted] == ["queued", "queued"]


def test_normal_when_glossary_preset(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """glossary_preset で指定した用語集のプリセットの名前をジョブに持たせて積む（正常系）。"""
    # 準備: 設定に「既定」と「会議」があり、設定で選んでいるのは「既定」
    stack = web_stack(worker=False, settings=PRESET_SETTINGS)
    audio = make_audio("webm", tmp_path)

    # 実行: 「会議」を指定した送信と、項目なしの送信と、空文字の送信
    specified = stack.post_audio(audio, glossary_preset="会議")
    omitted = stack.post_audio(audio)
    empty = stack.post_audio(audio, glossary_preset="")

    # 検証
    assert specified.status_code == 202
    assert stack.web_queue.get(specified.json()["job_id"]).glossary_preset == "会議"
    assert omitted.status_code == 202
    assert stack.web_queue.get(omitted.json()["job_id"]).glossary_preset is None
    assert empty.status_code == 202
    assert stack.web_queue.get(empty.json()["job_id"]).glossary_preset is None


def test_error_when_glossary_preset_not_found(
    web_stack: Callable[..., Stack], tmp_path: Path
) -> None:
    """設定の一覧に無い用語集のプリセットを指定した音声を、積まずに断る（異常系）。"""
    # 準備
    stack = web_stack(worker=False, settings=PRESET_SETTINGS)

    # 実行
    response = stack.post_audio(make_audio("webm", tmp_path), glossary_preset="無いプリセット")

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "無いプリセット" in response.json()["detail"]
    assert list(stack.web_tmp_dir.iterdir()) == []
    assert stack.web_queue._jobs == {}  # noqa: SLF001 積んだジョブが無いことを確かめる


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param(None, id="without_origin"),
        pytest.param("http://evil.example", id="not_allowed_origin"),
    ],
)
def test_error_when_running_on_linux(linux_stack: Stack, tmp_path: Path, origin: str | None) -> None:
    """常駐サービスが Linux で動いているときは、Origin によらず 404 を返し、ジョブを積まない（異常系）。"""
    # 準備
    audio = make_audio("webm", tmp_path)

    # 実行
    response = linux_stack.post_audio(audio, origin=origin)

    # 検証
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert list(linux_stack.web_tmp_dir.iterdir()) == []
