"""単一ユースケース「起こした文字を届ける」のうち、カスタムプリセットの E2E テスト。

本物の常駐アプリ（`python -m voice_paste --data-dir {一時フォルダ}`）を起動し、録音の画面のプリセットのボタンで確定して、
ブラウザ添付は Edge のアプリのウィンドウで開く 127.0.0.1 の画面（`tests/support/browser_target.py`）へ、
エンドポイントへ送るは 127.0.0.1 のテスト用の受け口へ、起こした文字が届くまでを確かめる。
普段使いのアプリや外の送り先へは送らない。実機のマイクで録音する（`--run-e2e` が無ければ skip する）。

固定の出力先（貼り付けて送信・貼り付けのみ・コピーのみ）と呼び出し元へ返すは、複合ユースケースの E2E
（`test_paste_voice_text.py`・`test_transcribe_from_other_system.py`）と「録音する」の E2E で通るため、ここでは作らない。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.app_driver import AppDriver
from tests.support.browser_target import BrowserTarget
from tests.support.desktop import PasteTarget, wait_until
from tests.support.flows import (
    API_QUIET_SEC,
    BROWSER_APPLIED_TIMEOUT_SEC,
    PASTE_AND_SEND_ONLY,
    PRESET_BUTTON,
    SLOW_RECEIVER_SEC,
    begin_recording,
    browser_preset_settings,
    endpoint_preset_settings,
    speak_and_confirm,
    wait_processed,
)

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]

BROWSER_QUIET_SEC = 2.0
"""開き先の画面に文字が入った後、Enter が送られないことを確かめるために待つ秒数。"""

NO_ENTER_DELAY_SEC = 0.5
"""貼り付けてから Enter を送るまでの設定の間（貼り付けて送信の既定）。"""


def _applied(target: BrowserTarget, *, entered: bool) -> bool:
    """開き先の画面の入力欄に文字が入り、entered なら Enter が送られているか。"""
    return target.text() != "" and (target.enters() >= 1 if entered else True)


def test_normal_when_browser_preset(
    start_app: StartApp, browser_target: BrowserTarget, clipboard_sentinel: str
) -> None:
    """Enter まで送るブラウザ添付のプリセットで確定すると、URL の画面がアプリのウィンドウで開き、入力欄に起こした文字が入って送信される（正常シナリオ）。"""
    # 準備
    app = start_app(
        PASTE_AND_SEND_ONLY + browser_preset_settings(browser_target.url, send_enter=True)
    )
    begin_recording(app)

    # 実行
    speak_and_confirm(app, output=PRESET_BUTTON)

    # 検証
    assert app.wait_window_gone("recording_window")
    assert wait_until(
        lambda: _applied(browser_target, entered=True), BROWSER_APPLIED_TIMEOUT_SEC
    ), "開き先の画面の入力欄に文字が入らなかった（スピーカーの音をマイクが拾えない・Edge が前面に出ない環境ではないか）"
    wait_processed(app)
    assert browser_target.page_requests >= 1
    assert browser_target.window_open()
    assert browser_target.enters() == 1
    assert pyperclip.paste() == browser_target.text()
    assert len(app.service.history_files(".wav")) == 1
    assert len(app.service.history_files(".txt")) == 1


def test_normal_when_browser_preset_without_enter(
    start_app: StartApp, browser_target: BrowserTarget, clipboard_sentinel: str
) -> None:
    """Enter まで送らないブラウザ添付のプリセットで確定すると、入力欄に起こした文字が入り、送信はされない（正常シナリオ）。"""
    # 準備
    app = start_app(
        PASTE_AND_SEND_ONLY + browser_preset_settings(browser_target.url, send_enter=False)
    )
    begin_recording(app)

    # 実行
    speak_and_confirm(app, output=PRESET_BUTTON)

    # 検証
    assert app.wait_window_gone("recording_window")
    assert wait_until(
        lambda: _applied(browser_target, entered=False), BROWSER_APPLIED_TIMEOUT_SEC
    ), "開き先の画面の入力欄に文字が入らなかった（スピーカーの音をマイクが拾えない・Edge が前面に出ない環境ではないか）"
    wait_processed(app)
    time.sleep(NO_ENTER_DELAY_SEC + BROWSER_QUIET_SEC)
    assert browser_target.window_open()
    assert browser_target.enters() == 0
    assert pyperclip.paste() == browser_target.text()


def test_normal_when_endpoint_preset(
    start_app: StartApp,
    receiver: CallbackReceiver,
    paste_target: PasteTarget,
    clipboard_sentinel: str,
) -> None:
    """エンドポイントへ送るプリセットで確定すると、送り先に ID と起こした文字が 1 回届き、クリップボードと貼り付け先は変わらない（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY + endpoint_preset_settings(receiver.url))
    begin_recording(app, paste_target)

    # 実行
    speak_and_confirm(app, output=PRESET_BUTTON)

    # 検証
    assert app.wait_window_gone("recording_window")
    assert wait_until(lambda: len(receiver.received) >= 1, BROWSER_APPLIED_TIMEOUT_SEC)
    wait_processed(app)
    time.sleep(API_QUIET_SEC)
    assert len(receiver.received) == 1
    payload = receiver.received[0]
    assert payload["session_id"] != ""
    assert payload["result"] == "transcribed"
    assert payload["text"] != "", "起こした文字が空だった（スピーカーの音をマイクが拾えない環境ではないか）"
    assert payload["error"] is None
    assert pyperclip.paste() == clipboard_sentinel
    assert paste_target.text() == ""
    assert paste_target.enters() == 0


def test_error_when_endpoint_unreachable(
    start_app: StartApp,
    receiver: CallbackReceiver,
    paste_target: PasteTarget,
    clipboard_sentinel: str,
) -> None:
    """送り先に届かなければ、送り直さず、届けられなかったことをトレイとログで知らせ、録音と起こした文字は履歴に残って待機中に戻る（異常シナリオ）。

    送り先は、受け取っても応えない受け口（既定のタイムアウトより長く待たせる）にして、送った回数を数える。
    """
    # 準備
    receiver.delay_sec = SLOW_RECEIVER_SEC
    app = start_app(PASTE_AND_SEND_ONLY + endpoint_preset_settings(receiver.url))
    begin_recording(app, paste_target)

    # 実行
    speak_and_confirm(app, output=PRESET_BUTTON)

    # 検証
    assert app.wait_window_gone("recording_window")
    assert wait_until(lambda: app.notified("delivery_failed"), BROWSER_APPLIED_TIMEOUT_SEC)
    wait_processed(app)
    time.sleep(SLOW_RECEIVER_SEC)
    assert len(receiver.received) == 1
    assert any(message.startswith("出力先へ届けられなかった（") for message in app.log_messages("ERROR"))
    assert len(app.service.history_files(".wav")) == 1
    assert len(app.service.history_files(".txt")) == 1
    assert pyperclip.paste() == clipboard_sentinel
    # 続けて録音を始められる
    begin_recording(app, paste_target)
    app.press("cancel_button")
    assert app.wait_window_gone("recording_window")
