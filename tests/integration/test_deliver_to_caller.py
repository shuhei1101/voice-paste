"""呼び出し元へ返す（返送先への POST）の結合テスト。

API の開始・停止・完了を本物の app へ呼んで、起こした文字などが返送先のテスト用の受け口へ届くまでを確かめる。
マイク・システム音量・文字起こしのエンジンは偽物。再送の間隔だけ短くしてある。
"""

from __future__ import annotations

import logging

import pytest

from tests.integration.helpers import START, SESSION_LIMIT, Stack
from voice_paste.features.outputs.callback.service import CALLBACK_RETRY_COUNT
from voice_paste.shared.errors import EngineError

RECEIVER_DELAY_SEC = 1.0
"""受け口が返送を受け取ってから 2xx を返すまでの取り決めの上限（非機能要件の返送のタイムアウトと再送）。"""


def _complete_session(stack: Stack) -> str:
    """API で開始・停止・完了を呼び、セッションの ID を返す。"""
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")
    assert stack.post(f"/sessions/{session_id}/complete").status_code == 202
    return session_id


def test_normal(stack: Stack) -> None:
    """起こした文字を返送先へ送る（正常系）。"""
    # 準備
    stack.engine.segments = ["てすと"]

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert stack.receiver.received == [
        {"session_id": session_id, "result": "transcribed", "text": "てすと", "error": None}
    ]


def test_normal_when_empty(stack: Stack) -> None:
    """空の文字を返送先へ送る（正常系）。"""
    # 準備
    stack.engine.segments = []

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert stack.receiver.received == [
        {"session_id": session_id, "result": "transcribed", "text": "", "error": None}
    ]


def test_normal_when_transcription_failed(stack: Stack) -> None:
    """文字起こしの失敗を返送先へ送る（正常系）。"""
    # 準備
    stack.engine.error = EngineError("エンジンが落ちた")

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert len(stack.receiver.received) == 1
    payload = stack.receiver.received[0]
    assert payload["session_id"] == session_id
    assert payload["result"] == "failed"
    assert payload["text"] == ""
    assert "エンジンが落ちた" in payload["error"]


def test_normal_when_truncated(stack: Stack) -> None:
    """完了が来ないまま上限で打ち切ったことを返送先へ送る（正常系）。"""
    # 準備
    session_id = stack.start_session()
    stack.clock.current = START + SESSION_LIMIT

    # 実行
    truncated = stack.manager.truncate_if_expired()

    # 検証
    assert truncated is True
    assert stack.wait_for_idle()
    assert stack.receiver.received == [
        {"session_id": session_id, "result": "truncated", "text": "", "error": None}
    ]


def test_error_when_callback_unreachable(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    """決めた回数まで再送しても届かなければログに書いて終える（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    stack.receiver.default_status = 500

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert len(stack.receiver.received) == 1 + CALLBACK_RETRY_COUNT
    errors = [
        record.getMessage() for record in caplog.records if record.levelno == logging.ERROR
    ]
    assert any(session_id in message for message in errors)


def test_normal_when_receiver_waits_one_second(stack: Stack) -> None:
    """受け口が 1 秒待ってから 2xx を返しても再送されない（正常系）。"""
    # 準備
    stack.receiver.delay_sec = RECEIVER_DELAY_SEC

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert [payload["session_id"] for payload in stack.receiver.received] == [session_id]
