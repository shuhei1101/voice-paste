"""features/outputs/types.py（ResultPayload・CallbackPayload）の単体テスト。"""

from __future__ import annotations


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
