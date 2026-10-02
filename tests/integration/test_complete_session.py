"""録音を完了する（POST /sessions/{session_id}/complete）の結合テスト。

本物の app を 127.0.0.1 の空きポートに立て、httpx で叩く。マイク・システム音量・文字起こしのエンジンは偽物。
"""

from __future__ import annotations

import logging

import pytest

from tests.integration.helpers import VOLUME_BEFORE, Stack

TOKEN_MISMATCH_HEADERS = [
    pytest.param({}, id="no_authorization"),
    pytest.param({"Authorization": "Bearer wrong-token"}, id="wrong_token"),
]
BROWSER_REQUEST_HEADERS = [
    pytest.param({"Origin": "http://evil.example"}, id="origin"),
    pytest.param({"Host": "evil.example"}, id="host"),
]


def test_normal(stack: Stack) -> None:
    """止めた録音を確定し、文字起こしを始める（正常系）。"""
    # 準備
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete")

    # 検証
    assert response.status_code == 202
    assert stack.wait_for_received(1)
    assert len(stack.recordings()) == 1
    assert stack.engine.audio_paths == stack.recordings()


def test_normal_when_recording(stack: Stack) -> None:
    """停止せずに完了すると、録音を止めてから確定する（正常系）。"""
    # 準備
    session_id = stack.start_session()

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete")

    # 検証
    assert response.status_code == 202
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.wait_for_received(1)
    assert len(stack.recordings()) == 1


@pytest.mark.parametrize("headers", TOKEN_MISMATCH_HEADERS)
def test_error_when_token_mismatch(
    stack: Stack, caplog: pytest.LogCaptureFixture, headers: dict[str, str]
) -> None:
    """トークンが合わなければ確定しない（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete", headers=headers, authorized=False)

    # 検証
    assert response.status_code == 401
    assert stack.state() == "stopped"
    assert stack.engine.audio_paths == []
    assert "Host" in caplog.text
    assert stack.token not in caplog.text


@pytest.mark.parametrize("headers", BROWSER_REQUEST_HEADERS)
def test_error_when_browser_request(
    stack: Stack, caplog: pytest.LogCaptureFixture, headers: dict[str, str]
) -> None:
    """Origin の付いた要求と、Host が待ち受けのホストでない要求を断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete", headers=headers)

    # 検証
    assert response.status_code == 403
    assert stack.state() == "stopped"
    assert stack.engine.audio_paths == []
    assert "Host" in caplog.text
    assert stack.token not in caplog.text


def test_error_when_session_unknown(stack: Stack) -> None:
    """録音中でも停止中でもないセッションは断る（異常系）。"""
    # 準備
    stack.manager.start("hotkey")

    # 実行
    response = stack.post("/sessions/unknown-session-id/complete")

    # 検証
    assert response.status_code == 404
    assert stack.engine.audio_paths == []
    assert stack.state() == "recording"
    assert stack.session().entry == "hotkey"
