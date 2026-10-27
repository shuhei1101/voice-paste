"""上限で打ち切るの結合テスト。

上限時間を短い値に差し替え、時計を進めて打ち切る。マイク・システム音量・返送先の受信先は偽物（受信先は 127.0.0.1 のテスト用）。
"""

from __future__ import annotations

import logging

import pytest

from tests.integration.helpers import (
    CONTINUOUS_SESSION_LIMIT,
    SESSION_LIMIT,
    START,
    VOLUME_BEFORE,
    Stack,
)


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


def test_normal_when_continuous(stack: Stack, caplog: pytest.LogCaptureFixture) -> None:
    """連続録音の上限時間に達したら録音を停止し、残りの話し声を最後の区間として届けた後に打ち切ったことを通知する（正常系）。"""
    # 準備: 区間を 1 つ区切った後、話し声が続いている間に連続録音の上限時間が経つ
    caplog.set_level(logging.WARNING)
    stack.set_segments(1, tail=0.9)
    session_id = stack.start_session(continuous=True)
    stack.feed_segments(1)
    assert stack.wait_for_received(1)
    stack.microphone.feed(1.0)
    # 1 回の録音の上限時間では打ち切らない
    stack.clock.current = START + SESSION_LIMIT
    assert stack.manager.truncate_if_expired() is False
    stack.clock.current = START + CONTINUOUS_SESSION_LIMIT

    # 実行
    truncated = stack.manager.truncate_if_expired()

    # 検証
    assert truncated is True
    assert stack.microphone.streams[0].closed
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.wait_for_idle()
    assert [path.stem.rsplit("_", 1)[1] for path in stack.recordings()] == ["1", "2"]
    assert [(p["result"], p["segment_number"], p["segment_count"]) for p in stack.receiver.received] == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("truncated", None, 2),
    ]
    assert session_id in caplog.text
    assert stack.post("/sessions", json_body={"callback_url": stack.receiver.url}).status_code == 202
