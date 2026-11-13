"""録音を停止する（POST /sessions/{session_id}/stop）の結合テスト。

本物の app を 127.0.0.1 の空きポートに立て、httpx で叩く。マイク・システム音量・文字起こしのエンジンは偽物。
"""

from __future__ import annotations

import logging

import pytest

from tests.integration.helpers import SAMPLE_RATE, VOLUME_BEFORE, Stack

TOKEN_MISMATCH_HEADERS = [
    pytest.param({}, id="no_authorization"),
    pytest.param({"Authorization": "Bearer wrong-token"}, id="wrong_token"),
]
BROWSER_REQUEST_HEADERS = [
    pytest.param({"Origin": "http://evil.example"}, id="origin"),
    pytest.param({"Host": "evil.example"}, id="host"),
]
FED_SEC = 1.0


def test_normal(stack: Stack) -> None:
    """録音中の録音セッションを停止する（正常系）。"""
    # 準備
    session_id = stack.start_session()
    stack.microphone.feed(FED_SEC)

    # 実行
    response = stack.post(f"/sessions/{session_id}/stop")
    stack.microphone.feed(FED_SEC)

    # 検証
    assert response.status_code == 200
    assert stack.state() == "stopped"
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.display.calls == ["inhibit", "release"]
    assert stack.session().recording.samples.size == int(SAMPLE_RATE * FED_SEC)


def test_error_when_continuous(stack: Stack) -> None:
    """連続録音の録音セッションは停止せずに断る（異常系）。"""
    # 準備
    stack.set_segments(1)
    session_id = stack.start_session(continuous=True)

    # 実行
    response = stack.post(f"/sessions/{session_id}/stop")
    stack.feed_segments(1)

    # 検証: 409 で連続録音は完了で終えることを伝え、録音は止まらず区切りを続ける
    assert response.status_code == 409
    assert "完了" in response.json()["detail"]
    assert stack.state() == "recording"
    assert not stack.microphone.streams[0].closed
    assert stack.wait_for_received(1)
    assert stack.receiver.received[0]["segment_number"] == 1


def test_normal_when_already_stopped(stack: Stack) -> None:
    """停止した録音セッションへの停止は何も変えず 200 を返す（正常系）。"""
    # 準備
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")

    # 実行
    response = stack.post(f"/sessions/{session_id}/stop")

    # 検証
    assert response.status_code == 200
    assert stack.state() == "stopped"
    assert stack.display.calls.count("release") == 1


@pytest.mark.parametrize("headers", TOKEN_MISMATCH_HEADERS)
def test_error_when_token_mismatch(
    stack: Stack, caplog: pytest.LogCaptureFixture, headers: dict[str, str]
) -> None:
    """トークンが合わなければ停止しない（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    session_id = stack.start_session()

    # 実行
    response = stack.post(f"/sessions/{session_id}/stop", headers=headers, authorized=False)

    # 検証
    assert response.status_code == 401
    assert stack.state() == "recording"
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

    # 実行
    response = stack.post(f"/sessions/{session_id}/stop", headers=headers)

    # 検証
    assert response.status_code == 403
    assert stack.state() == "recording"
    assert "Host" in caplog.text
    assert stack.token not in caplog.text


def test_error_when_session_unknown(stack: Stack) -> None:
    """録音中でも停止中でもない録音セッションは断る（異常系）。"""
    # 準備
    stack.manager.start("hotkey")

    # 実行
    response = stack.post("/sessions/unknown-session-id/stop")

    # 検証
    assert response.status_code == 404
    assert stack.state() == "recording"
    assert stack.session().entry == "hotkey"
