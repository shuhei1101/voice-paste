"""features/outputs/service.py（deliver）の単体テスト。

出力先の関数（handler）は Mock にして、どれが呼ばれたかだけを確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
        None,
        CALLBACK_URL,
        outcome,
        enabled_ids=frozenset({"paste_and_send"}),
        outputs=outputs,
    )

    # 検証
    callback.assert_called_once_with(outcome, CALLBACK_URL)
    paste_and_send.assert_not_called()


def test_deliver_when_hotkey_session() -> None:
    """ホットキーのセッションは選んだ出力先へ届ける（正常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    paste_only = MagicMock()
    callback = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="paste_only", title="貼り付けのみ", handler=paste_only),
        OutputSpec(id="callback", title="呼び出し元へ返す", handler=callback, api_only=True),
    ]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行
    deliver(
        "hotkey",
        "paste_only",
        None,
        None,
        outcome,
        enabled_ids=frozenset({"paste_and_send", "paste_only"}),
        outputs=outputs,
    )

    # 検証
    paste_only.assert_called_once_with(outcome, None)
    paste_and_send.assert_not_called()
    callback.assert_not_called()


def test_deliver_when_output_disabled() -> None:
    """オフの出力先は届けない（異常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec
    from voice_paste.shared.errors import UnknownOutputError
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    ai_chat = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="ai_chat", title="AI チャットへ送る", handler=ai_chat),
    ]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行・検証
    with pytest.raises(UnknownOutputError, match="ai_chat"):
        deliver(
            "hotkey",
            "ai_chat",
            "https://chatgpt.com",
            None,
            outcome,
            enabled_ids=frozenset({"paste_and_send"}),
            outputs=outputs,
        )
    paste_and_send.assert_not_called()
    ai_chat.assert_not_called()


def test_deliver_when_output_target() -> None:
    """選んだ送り先を宛先として渡す（正常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    ai_chat = MagicMock()
    callback = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="ai_chat", title="AI チャットへ送る", handler=ai_chat),
        OutputSpec(id="callback", title="呼び出し元へ返す", handler=callback, api_only=True),
    ]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行
    deliver(
        "hotkey",
        "ai_chat",
        "https://chatgpt.com",
        None,
        outcome,
        enabled_ids=frozenset({"paste_and_send", "ai_chat"}),
        outputs=outputs,
    )

    # 検証
    ai_chat.assert_called_once_with(outcome, "https://chatgpt.com")
    paste_and_send.assert_not_called()
    callback.assert_not_called()
