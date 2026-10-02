"""上限で打ち切るの結合テスト。

上限時間を短い値に差し替え、時計を進めて打ち切る。マイク・システム音量・返送先の受け口は偽物（受け口は 127.0.0.1 のテスト用）。
"""

from __future__ import annotations

import logging

import pytest

from tests.integration.helpers import SESSION_LIMIT, START, VOLUME_BEFORE, Stack


def test_normal(stack: Stack, caplog: pytest.LogCaptureFixture) -> None:
    """録音中のまま上限に達したセッションを打ち切る（正常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    session_id = stack.start_session()
    stack.microphone.feed(1.0)
    stack.clock.current = START + SESSION_LIMIT

    # 実行
    truncated = stack.manager.truncate_if_expired()

    # 検証
    assert truncated is True
    assert stack.microphone.streams[0].closed
    assert stack.volume.level == VOLUME_BEFORE
    assert len(stack.recordings()) == 1
    assert stack.wait_for_received(1)
    assert stack.receiver.received[0]["result"] == "truncated"
    assert session_id in caplog.text
    assert stack.engine.audio_paths == []
    assert stack.wait_for_idle()


def test_normal_when_stopped(stack: Stack) -> None:
    """停止したまま完了が来ないセッションも、開始からの経過時間で打ち切る（正常系）。"""
    # 準備
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")
    stack.clock.current = START + SESSION_LIMIT

    # 実行
    truncated = stack.manager.truncate_if_expired()

    # 検証
    assert truncated is True
    assert len(stack.recordings()) == 1
    assert stack.wait_for_received(1)
    assert stack.receiver.received[0]["result"] == "truncated"
    assert stack.wait_for_idle()
    assert stack.post("/sessions", json_body={"callback_url": stack.receiver.url}).status_code == 202
