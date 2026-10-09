"""features/outputs/browser/service.py（send_to_browser）の単体テスト。

クリップボード（copy）・画面を開く（open_window）・貼り付けのキー（paste）・Enter（send_enter）・間（sleep）は、
呼ばれた順を 1 本の列で見られる Mock にして、順序と引数を確かめる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest

from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome

if TYPE_CHECKING:
    from voice_paste.shared.settings import BrowserPreset

URL = "https://chatgpt.com"
OPEN_DELAY_SEC = 3.0
ENTER_DELAY_SEC = 0.5


def _outcome() -> TranscriptionOutcome:
    """届ける結果（起こした文字「テスト」）を作る。"""
    return TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )


def _preset(*, send_enter: bool) -> BrowserPreset:
    """URL が https://chatgpt.com のブラウザ添付のプリセットを作る。"""
    from voice_paste.shared.settings import BrowserPreset

    return BrowserPreset(title="ChatGPT", url=URL, send_enter=send_enter)


def test_send_to_browser() -> None:
    """Enter まで送るプリセットは、コピー・開く・待ち・貼り付け・待ち・Enter の順に送る（正常系）。"""
    from voice_paste.features.outputs.browser.service import send_to_browser

    # 準備
    parent = MagicMock()
    get_open_delay_sec = MagicMock(return_value=OPEN_DELAY_SEC)
    get_enter_delay_sec = MagicMock(return_value=ENTER_DELAY_SEC)

    # 実行
    send_to_browser(
        _outcome(),
        _preset(send_enter=True),
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
        call.open_window(URL),
        call.sleep(OPEN_DELAY_SEC),
        call.paste(),
        call.sleep(ENTER_DELAY_SEC),
        call.send_enter(),
    ]


def test_send_to_browser_when_paste_only() -> None:
    """Enter まで送らないプリセットは貼り付けで止める（正常系）。"""
    from voice_paste.features.outputs.browser.service import send_to_browser

    # 準備
    parent = MagicMock()
    get_open_delay_sec = MagicMock(return_value=OPEN_DELAY_SEC)
    get_enter_delay_sec = MagicMock(return_value=ENTER_DELAY_SEC)

    # 実行
    send_to_browser(
        _outcome(),
        _preset(send_enter=False),
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
        call.open_window(URL),
        call.sleep(OPEN_DELAY_SEC),
        call.paste(),
    ]
    parent.send_enter.assert_not_called()
    get_enter_delay_sec.assert_not_called()


def test_send_to_browser_when_open_failed() -> None:
    """画面を開けなければ貼り付けない（異常系）。"""
    from voice_paste.features.outputs.browser.service import send_to_browser

    # 準備
    copy = MagicMock()
    open_window = MagicMock(side_effect=DeliveryError("画面を開けない"))
    paste = MagicMock()
    send_enter = MagicMock()
    sleep = MagicMock()

    # 実行・検証
    with pytest.raises(DeliveryError, match="画面を開けない"):
        send_to_browser(
            _outcome(),
            _preset(send_enter=True),
            copy=copy,
            open_window=open_window,
            paste=paste,
            send_enter=send_enter,
            sleep=sleep,
            get_open_delay_sec=MagicMock(return_value=OPEN_DELAY_SEC),
            get_enter_delay_sec=MagicMock(return_value=ENTER_DELAY_SEC),
        )
    paste.assert_not_called()
    send_enter.assert_not_called()
