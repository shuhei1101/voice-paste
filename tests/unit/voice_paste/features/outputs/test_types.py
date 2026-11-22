"""features/outputs/types.py（ResultPayload・CallbackPayload）の単体テスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone


def test_result_payload_from_outcome() -> None:
    """結果をコピーする（正常系）。"""
    from voice_paste.features.outputs.types import ResultPayload
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    outcome = TranscriptionOutcome(
        session_id="s1", result="transcribed", text="テスト", error=None
    )

    # 実行
    payload = ResultPayload.from_outcome(outcome)

    # 検証
    assert payload.model_dump() == {
        "session_id": "s1",
        "result": "transcribed",
        "text": "テスト",
        "error": None,
    }


def test_callback_payload_from_outcome() -> None:
    """区間の結果をコピーする（正常系）。"""
    from voice_paste.features.outputs.types import CallbackPayload
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    outcome = TranscriptionOutcome(
        session_id="s1", result="transcribed", text="テスト", error=None, segment_number=2
    )

    # 実行
    payload = CallbackPayload.from_outcome(outcome)

    # 検証
    assert payload.model_dump() == {
        "session_id": "s1",
        "result": "transcribed",
        "text": "テスト",
        "error": None,
        "segment_number": 2,
        "segment_count": None,
        "started_at": None,
        "ended_at": None,
    }


def test_callback_payload_from_outcome_when_single() -> None:
    """1 回の録音の結果は通し番号と区間の数が None（正常系）。"""
    from voice_paste.features.outputs.types import CallbackPayload
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    outcome = TranscriptionOutcome(
        session_id="s1", result="transcribed", text="テスト", error=None
    )

    # 実行
    payload = CallbackPayload.from_outcome(outcome)

    # 検証
    assert payload.segment_number is None
    assert payload.segment_count is None
    assert payload.started_at is None
    assert payload.ended_at is None


def test_callback_payload_serializes_times() -> None:
    """区間の時刻を UTC の ISO 8601（ミリ秒まで・末尾 Z）で送信する（正常系）。"""
    from voice_paste.features.outputs.types import CallbackPayload
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備: 話し始めは日本時間、話し終わりは UTC で持つ
    outcome = TranscriptionOutcome(
        session_id="s1",
        result="transcribed",
        text="テスト",
        error=None,
        segment_number=1,
        started_at=datetime(2026, 11, 21, 21, 0, 3, 120456, tzinfo=timezone(timedelta(hours=9))),
        ended_at=datetime(2026, 11, 21, 12, 0, 5, 480000, tzinfo=UTC),
    )

    # 実行
    dumped = CallbackPayload.from_outcome(outcome).model_dump(mode="json")

    # 検証
    assert dumped["started_at"] == "2026-11-21T12:00:03.120Z"
    assert dumped["ended_at"] == "2026-11-21T12:00:05.480Z"
