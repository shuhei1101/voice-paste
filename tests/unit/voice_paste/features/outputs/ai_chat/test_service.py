"""features/outputs/ai_chat/service.py（send_to_ai_chat）の単体テスト。

クリップボード（copy）・画面を開く（open_window）・貼り付けのキー（paste）・Enter（send_enter）・間（sleep）は、
呼ばれた順を 1 本の列で見られる Mock にして、順序と引数を確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome

TARGET = "https://chatgpt.com"


def _outcome() -> TranscriptionOutcome:
    """届ける結果（起こした文字「テスト」）を作る。"""
    return TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )


def test_send_to_ai_chat() -> None:
    """コピー・開く・待ち・貼り付け・待ち・Enter の順に送る（正常系）。"""
    from voice_paste.features.outputs.ai_chat.service import send_to_ai_chat

    # 準備
    parent = MagicMock()
    get_open_delay_sec = MagicMock(return_value=3.0)
    get_enter_delay_sec = MagicMock(return_value=0.5)

    # 実行
    send_to_ai_chat(
        _outcome(),
        TARGET,
        copy=parent.copy,
        open_window=parent.open_window,
        paste=parent.paste,
        send_enter=parent.send_enter,
        sleep=parent.sleep,
        get_open_delay_sec=get_open_delay_sec,
        get_enter_delay_sec=get_enter_delay_sec,
    )

    # 検証
    assert parent.mock_calls == [
        call.copy("テスト"),
        call.open_window(TARGET),
        call.sleep(3.0),
        call.paste(),
        call.sleep(0.5),
        call.send_enter(),
    ]


def test_send_to_ai_chat_when_no_target() -> None:
    """送り先が無ければ何もしない（異常系）。"""
    from voice_paste.features.outputs.ai_chat.service import send_to_ai_chat

    # 準備
    copy = MagicMock()
    open_window = MagicMock()
    paste = MagicMock()
    send_enter = MagicMock()
    sleep = MagicMock()

    # 実行・検証
    with pytest.raises(DeliveryError):
        send_to_ai_chat(
            _outcome(),
            None,
            copy=copy,
            open_window=open_window,
            paste=paste,
            send_enter=send_enter,
            sleep=sleep,
            get_open_delay_sec=MagicMock(return_value=3.0),
            get_enter_delay_sec=MagicMock(return_value=0.5),
        )
    copy.assert_not_called()
    open_window.assert_not_called()


def test_send_to_ai_chat_when_open_failed() -> None:
    """画面を開けなければ貼り付けない（異常系）。"""
    from voice_paste.features.outputs.ai_chat.service import send_to_ai_chat

    # 準備
    copy = MagicMock()
    open_window = MagicMock(side_effect=DeliveryError("画面を開けない"))
    paste = MagicMock()
    send_enter = MagicMock()
    sleep = MagicMock()

    # 実行・検証
    with pytest.raises(DeliveryError, match="画面を開けない"):
        send_to_ai_chat(
            _outcome(),
            TARGET,
            copy=copy,
            open_window=open_window,
            paste=paste,
            send_enter=send_enter,
            sleep=sleep,
            get_open_delay_sec=MagicMock(return_value=3.0),
            get_enter_delay_sec=MagicMock(return_value=0.5),
        )
    paste.assert_not_called()
    send_enter.assert_not_called()
