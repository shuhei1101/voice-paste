"""呼び出し元へ返す（コールバック先への POST）の結合テスト。

API の開始・停止・完了を本物の app へ呼んで、起こした文字などがコールバック先のテスト用の受信先へ届くまでを確かめる。
マイク・システム音量・文字起こしのエンジンは偽物。再送の間隔だけ短くしてある。
"""

from __future__ import annotations

import logging

import pytest

from tests.integration.helpers import (
    SEGMENT_PHASES,
    SESSION_LIMIT,
    START,
    VOLUME_BEFORE,
    Stack,
)
from voice_paste.features.outputs.callback.service import CALLBACK_RETRY_COUNT
from voice_paste.shared.errors import EngineError

RECEIVER_DELAY_SEC = 1.0
"""受信先が返送を受け取ってから 2xx を返すまでの取り決めの上限（非機能要件の返送のタイムアウトと再送）。"""


def _complete_session(stack: Stack) -> str:
    """API で開始・停止・完了を呼び、録音セッションの ID を返す。"""
    session_id = stack.start_session()
    stack.post(f"/sessions/{session_id}/stop")
    assert stack.post(f"/sessions/{session_id}/complete").status_code == 202
    return session_id


def test_normal(stack: Stack) -> None:
    """起こした文字をコールバック先へ送信する（正常系）。"""
    # 準備
    stack.engine.segments = ["てすと"]

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert stack.receiver.received == [
        {
            "session_id": session_id,
            "result": "transcribed",
            "text": "てすと",
            "error": None,
            "segment_number": None,
            "segment_count": None,
        }
    ]


def test_normal_when_empty(stack: Stack) -> None:
    """空の文字をコールバック先へ送信する（正常系）。"""
    # 準備
    stack.engine.segments = []

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert stack.receiver.received == [
        {
            "session_id": session_id,
            "result": "transcribed",
            "text": "",
            "error": None,
            "segment_number": None,
            "segment_count": None,
        }
    ]


def test_normal_when_transcription_failed(stack: Stack) -> None:
    """文字起こしの失敗をコールバック先へ送信する（正常系）。"""
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
    """完了が来ないまま上限で打ち切ったことをコールバック先へ送信する（正常系）。"""
    # 準備
    session_id = stack.start_session()
    stack.clock.current = START + SESSION_LIMIT

    # 実行
    truncated = stack.manager.truncate_if_expired()

    # 検証
    assert truncated is True
    assert stack.wait_for_idle()
    assert stack.receiver.received == [
        {
            "session_id": session_id,
            "result": "truncated",
            "text": "",
            "error": None,
            "segment_number": None,
            "segment_count": None,
        }
    ]


def _rows(stack: Stack) -> list[tuple[str, int | None, int | None]]:
    """コールバック先に届いた中身を届いた順に、(result, segment_number, segment_count) の並びで返す。"""
    return [
        (payload["result"], payload["segment_number"], payload["segment_count"])
        for payload in stack.receiver.received
    ]


def test_normal_when_continuous_segment(stack: Stack) -> None:
    """連続録音で起こした区間の文字を、通し番号を付けて区切った順に送信する（正常系）。"""
    # 準備: 区間が 2 つ区切れる音を流す
    stack.set_segments(2)
    stack.start_session(continuous=True)

    # 実行
    stack.feed_segments(2)

    # 検証: 区間の返送が通し番号の順に届き、連続録音は続いている
    assert stack.wait_for_received(2)
    assert _rows(stack) == [("transcribed", 1, None), ("transcribed", 2, None)]
    assert [payload["text"] for payload in stack.receiver.received] == ["てすと", "てすと"]
    assert stack.state() == "recording"


def test_normal_when_continuous_segment_failed(stack: Stack) -> None:
    """連続録音の区間の文字起こしの失敗を通し番号つきで送信し、連続録音は続ける（正常系）。"""
    # 準備: 2 つ目の区間だけ文字起こしに失敗させる
    stack.engine.error_on_calls = {2}
    stack.set_segments(3)
    stack.start_session(continuous=True)

    # 実行
    stack.feed_segments(3)

    # 検証
    assert stack.wait_for_received(3)
    assert _rows(stack) == [
        ("transcribed", 1, None),
        ("failed", 2, None),
        ("transcribed", 3, None),
    ]
    failed = stack.receiver.received[1]
    assert failed["text"] == ""
    assert "失敗" in failed["error"]
    assert stack.state() == "recording"


def test_normal_when_continuous_completed(stack: Stack) -> None:
    """連続録音を完了すると、最後の区間を送信した後に完了したことと区間の数を送信する（正常系）。"""
    # 準備
    stack.set_segments(2)
    session_id = stack.start_session(continuous=True)
    stack.feed_segments(2)
    assert stack.wait_for_received(2)

    # 実行
    assert stack.post(f"/sessions/{session_id}/complete").status_code == 202

    # 検証
    assert stack.wait_for_idle()
    assert _rows(stack) == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("completed", None, 2),
    ]
    assert stack.receiver.received[2]["session_id"] == session_id
    assert stack.receiver.received[2]["text"] == ""


def test_normal_when_continuous_segmenter_failed(stack: Stack) -> None:
    """区切りに失敗して録音が止まった連続録音は、それまでの区間を送信した後に、失敗したことと理由・区間の数を送信する（正常系）。"""
    # 準備: 2 つの区間を区切った後の最初の窓の判定で例外を送出する
    cut_windows = sum(count for _, count in SEGMENT_PHASES) * 2
    stack.set_segments(2)
    stack.vad.fail_on_call = cut_windows + 1
    stack.vad.error = RuntimeError("VAD が落ちた")
    session_id = stack.start_session(continuous=True)

    # 実行
    stack.feed_segments(2)
    stack.microphone.feed(1.0)

    # 検証
    assert stack.wait_for_idle()
    assert _rows(stack) == [
        ("transcribed", 1, None),
        ("transcribed", 2, None),
        ("failed", None, 2),
    ]
    ending = stack.receiver.received[2]
    assert ending["text"] == ""
    assert "VAD が落ちた" in ending["error"]
    assert stack.microphone.streams[0].closed
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.post(f"/sessions/{session_id}/complete").status_code == 404


def test_error_when_continuous_segment_unreachable(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    """連続録音の区間が決めた回数まで再送しても届かなければ、ログに書いて次の区間へ進む（異常系）。"""
    # 準備: 1 つ目は届き、2 つ目の区間には常に 500 を返し、3 つ目からまた届く
    caplog.set_level(logging.WARNING)
    stack.receiver.statuses = [200] + [500] * (1 + CALLBACK_RETRY_COUNT)
    stack.set_segments(3)
    session_id = stack.start_session(continuous=True)

    # 実行
    stack.feed_segments(3)

    # 検証
    assert stack.wait_for_received(1 + (1 + CALLBACK_RETRY_COUNT) + 1)
    numbers = [payload["segment_number"] for payload in stack.receiver.received]
    assert numbers == [1] + [2] * (1 + CALLBACK_RETRY_COUNT) + [3]
    errors = [
        record.getMessage() for record in caplog.records if record.levelno == logging.ERROR
    ]
    assert any(session_id in message and "区間: 2" in message for message in errors)
    assert stack.state() == "recording"


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
    """受信先が 1 秒待ってから 2xx を返しても再送されない（正常系）。"""
    # 準備
    stack.receiver.delay_sec = RECEIVER_DELAY_SEC

    # 実行
    session_id = _complete_session(stack)

    # 検証
    assert stack.wait_for_idle()
    assert [payload["session_id"] for payload in stack.receiver.received] == [session_id]
