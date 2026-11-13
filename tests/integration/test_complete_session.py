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
    """停止した録音を確定し、文字起こしを始める（正常系）。"""
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
    """停止せずに完了すると、録音を停止してから確定する（正常系）。"""
    # 準備
    session_id = stack.start_session()

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete")

    # 検証
    assert response.status_code == 202
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.display.calls == ["inhibit", "release"]
    assert stack.wait_for_received(1)
    assert len(stack.recordings()) == 1


def test_normal_when_continuous(stack: Stack) -> None:
    """連続録音を完了すると、録音を止め、区間に切り出していない話し声を最後の区間として区切る（正常系）。"""
    # 準備: 区間を 1 つ区切った後、話し声が続いている間に完了を呼ぶ
    stack.set_segments(1, tail=0.9)
    session_id = stack.start_session(continuous=True)
    stack.feed_segments(1)
    assert stack.wait_for_received(1)
    stack.microphone.feed(1.0)

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete")
    again = stack.post(f"/sessions/{session_id}/complete")

    # 検証
    assert response.status_code == 202
    assert stack.microphone.streams[0].closed
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.display.calls == ["inhibit", "release"]
    assert stack.wait_for_idle()
    recordings = stack.recordings()
    assert [path.stem.rsplit("_", 1)[1] for path in recordings] == ["1", "2"]
    assert stack.engine.audio_paths == recordings
    assert again.status_code == 404


def test_normal_when_continuous_without_speech(stack: Stack) -> None:
    """話し声が残っていない連続録音を完了すると、最後の区間を作らずに終える（正常系）。"""
    # 準備: 無音だけを流す
    stack.set_segments(0)
    session_id = stack.start_session(continuous=True)
    stack.microphone.feed(3.0)

    # 実行
    response = stack.post(f"/sessions/{session_id}/complete")

    # 検証
    assert response.status_code == 202
    assert stack.wait_for_idle()
    assert stack.recordings() == []
    assert stack.engine.audio_paths == []
    assert [(p["result"], p["segment_number"], p["segment_count"]) for p in stack.receiver.received] == [
        ("completed", None, 0)
    ]


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
    """録音中でも停止中でもない録音セッションは断る（異常系）。"""
    # 準備
    stack.manager.start("hotkey")

    # 実行
    response = stack.post("/sessions/unknown-session-id/complete")

    # 検証
    assert response.status_code == 404
    assert stack.engine.audio_paths == []
    assert stack.state() == "recording"
    assert stack.session().entry == "hotkey"
