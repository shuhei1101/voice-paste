"""features/outputs/paste_and_send/service.py（paste_and_send）の単体テスト。

クリップボード（copy）・貼り付けのキー（paste）・Enter（send_enter）・間（sleep）は、
呼ばれた順を 1 本の列で見られる Mock にして、順序と引数を確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome


def _outcome() -> TranscriptionOutcome:
    """届ける結果（起こした文字「テスト」）を作る。"""
    return TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )


def test_paste_and_send() -> None:
    """コピー・貼り付け・待ち・Enter の順に送る（正常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import paste_and_send

    # 準備
    parent = MagicMock()
    get_enter_delay_sec = MagicMock(return_value=0.5)

    # 実行
    paste_and_send(
        _outcome(),
        None,
        copy=parent.copy,
        paste=parent.paste,
        send_enter=parent.send_enter,
        sleep=parent.sleep,
        get_enter_delay_sec=get_enter_delay_sec,
    )

    # 検証
    assert parent.mock_calls == [
        call.copy("テスト"),
        call.paste(),
        call.sleep(0.5),
        call.send_enter(),
    ]


def test_paste_and_send_when_copy_failed() -> None:
    """クリップボードへ書けなければキーを送らない（異常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import paste_and_send

    # 準備
    copy = MagicMock(side_effect=DeliveryError("クリップボードへ書けない"))
    paste = MagicMock()
    send_enter = MagicMock()
    sleep = MagicMock()
    get_enter_delay_sec = MagicMock(return_value=0.5)

    # 実行・検証
    with pytest.raises(DeliveryError, match="クリップボードへ書けない"):
        paste_and_send(
            _outcome(),
            None,
            copy=copy,
            paste=paste,
            send_enter=send_enter,
            sleep=sleep,
            get_enter_delay_sec=get_enter_delay_sec,
        )
    paste.assert_not_called()
    send_enter.assert_not_called()
