"""features/outputs/service.py（deliver）の単体テスト。

出力先の関数（handler）は Mock にして、どれが呼ばれたかだけを確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock

CALLBACK_URL = "http://127.0.0.1:9000/result"


def test_deliver_when_api_session() -> None:
    """API のセッションは呼び出し元へ返すだけ（正常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    callback = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="callback", title="呼び出し元へ返す", handler=callback, api_only=True),
    ]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行
    deliver(
        "api",
        None,
        CALLBACK_URL,
        outcome,
        enabled_ids=frozenset({"paste_and_send"}),
        outputs=outputs,
    )

    # 検証
    callback.assert_called_once_with(outcome, CALLBACK_URL)
    paste_and_send.assert_not_called()
