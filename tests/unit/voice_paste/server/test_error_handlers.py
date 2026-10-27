"""server/error_handlers.py（register_exception_handlers）の単体テスト。

build_fastapi が登録した例外ハンドラを、SessionManager を Mock にした app へ要求を送信して確かめる。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from tests.unit.voice_paste.server.helpers import (
    AUTHORIZATION,
    CALLBACK_URL,
    WEB_ORIGIN,
    make_client,
    make_web_client,
)
from voice_paste.shared.errors import SessionBusyError


def test_register_exception_handlers_when_validation_error() -> None:
    """URI でない callback_url は 400（正常系）。"""
    # 準備
    client, _session_manager = make_client()

    # 実行
    response = client.post("/sessions", json={"callback_url": "nope"}, headers=AUTHORIZATION)

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_register_exception_handlers_when_busy() -> None:
    """SessionBusyError は 409（正常系）。"""
    # 準備
    client, session_manager = make_client()
    session_manager.start.side_effect = SessionBusyError("処理中")

    # 実行
    response = client.post(
        "/sessions", json={"callback_url": CALLBACK_URL}, headers=AUTHORIZATION
    )

    # 検証
    assert response.status_code == 409


def test_register_exception_handlers_when_conflict() -> None:
    """SessionConflictError は 409 で、断った理由を detail に入れる（正常系）。"""
    from voice_paste.shared.errors import SessionConflictError

    # 準備
    client, session_manager = make_client()
    session_manager.stop.side_effect = SessionConflictError("連続録音は完了で終える")

    # 実行
    response = client.post("/sessions/session-1/stop", headers=AUTHORIZATION)

    # 検証
    assert response.status_code == 409
    assert response.json()["detail"] == "連続録音は完了で終える"


def _get_job(client: TestClient) -> Response:
    """結果の取得（GET）を送信する。"""
    return client.get("/web/transcriptions/missing")


def _post_audio(client: TestClient) -> Response:
    """音声の受け付け（POST）を送信する。"""
    return client.post(
        "/web/transcriptions",
        files={"audio": ("recording.webm", b"audio", "audio/webm")},
        headers={"Origin": WEB_ORIGIN},
    )


def _fail_get(queue: MagicMock, _probe_audio: MagicMock, error: Exception) -> None:
    """キューの結果の取得を error で失敗させる。"""
    queue.get.side_effect = error


def _fail_submit(queue: MagicMock, _probe_audio: MagicMock, error: Exception) -> None:
    """キューへの積みを error で失敗させる。"""
    queue.submit.side_effect = error


def _fail_probe(_queue: MagicMock, probe_audio: MagicMock, error: Exception) -> None:
    """音声の形式の読み取りを error で失敗させる。"""
    probe_audio.side_effect = error


@pytest.mark.parametrize(
    ("error_name", "fail", "send", "status"),
    [
        pytest.param("WebJobNotFoundError", _fail_get, _get_job, 404, id="job_not_found"),
        pytest.param("RequestBodyTooLargeError", _fail_submit, _post_audio, 413, id="body_too_large"),
        pytest.param("AudioUnreadableError", _fail_probe, _post_audio, 415, id="audio_unreadable"),
        pytest.param("WebQueueFullError", _fail_submit, _post_audio, 503, id="queue_full"),
    ],
)
def test_register_exception_handlers_when_web_errors(
    error_name: str,
    fail: Callable[[MagicMock, MagicMock, Exception], None],
    send: Callable[[TestClient], Response],
    status: int,
    tmp_path: Path,
) -> None:
    """ブラウザの API の例外を対応するステータスにする（正常系）。"""
    from voice_paste.shared import errors

    # 準備: route の先の関数が error_name の例外を送出する
    client, queue, probe_audio = make_web_client(tmp_path)
    fail(queue, probe_audio, getattr(errors, error_name)("理由"))

    # 実行
    response = send(client)

    # 検証
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
