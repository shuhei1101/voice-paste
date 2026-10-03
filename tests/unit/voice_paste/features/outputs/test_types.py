"""features/outputs/types.py（ResultPayload）の単体テスト。"""

from __future__ import annotations


def test_result_payload_from_outcome() -> None:
    """結果を写す（正常系）。"""
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
