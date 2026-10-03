"""単一ユースケース「録音を文字に起こす」の E2E テスト。

ホットキー・トレイから始めた録音は、トレイ・録音の画面を UI Automation で操作して貼り付け先まで確かめ、
API から始めた録音は、API を叩いて返送先に届く中身を確かめる（複合ユースケースと同じく、実機のマイクとローカルの Whisper を通す）。
起こした文字の中身は、スピーカーから読み上げた音をマイクが拾った結果で決まるため、決め打ちしない（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.app_driver import IDLE, WINDOW_TIMEOUT_SEC, AppDriver
from tests.support.desktop import (
    PasteTarget,
    explorer_locations,
    open_notification_center,
    wait_until,
)
from tests.support.flows import (
    FAILING_ENGINE_SETTINGS,
    NO_SPEECH_SETTINGS,
    PASTE_AND_SEND_ONLY,
    RECORD_SEC,
    begin_recording,
    kill_workers_twice,
    record_via_api,
    speak_and_confirm,
    wait_pasted,
    wait_processed,
)

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]

INDICATOR_WINDOW = "transcribing_indicator"
"""文字起こし中の表示の項目 ID。"""

NOTIFICATION_TITLE = "文字起こしに失敗しました"
"""文字起こしに失敗したときの通知の見出し。"""


def test_normal(start_app: StartApp, paste_target: PasteTarget) -> None:
    """確定した録音を文字に起こし、文字起こし中の表示を出し、起こした文字を履歴に書き足して貼り付け先へ届ける（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    begin_recording(app, paste_target)

    # 実行
    speak_and_confirm(app)

    # 検証
    shown = wait_until(lambda: app.window(INDICATOR_WINDOW) is not None, 30)
    assert wait_pasted(paste_target), "貼り付け先に文字が入らなかった（スピーカーの音をマイクが拾えない環境ではないか）"
    wait_processed(app)
    assert shown, "文字起こし中の表示が出なかった"
    assert app.window(INDICATOR_WINDOW) is None
    [text_file] = app.service.history_files(".txt")
    assert text_file.read_text(encoding="utf-8") == paste_target.text()


def test_normal_when_worker_dies(start_app: StartApp, paste_target: PasteTarget) -> None:
    """文字起こしワーカーが落ちても、立て直して文字起こしをやり直し、起こした文字を届ける（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    begin_recording(app, paste_target)
    speak_and_confirm(app)

    # 実行（立て直しを待つため、ワーカーを 1 度だけ止める）
    assert wait_until(lambda: app.kill_workers() >= 1, 60)

    # 検証
    assert wait_pasted(paste_target), "ワーカーを立て直しても貼り付け先に文字が入らなかった"
    wait_processed(app)
    assert app.service.is_running()
    assert len(app.worker_processes()) > 0


def test_error_when_worker_dies_again(start_app: StartApp, paste_target: PasteTarget) -> None:
    """やり直したワーカーも落ちると、失敗を知らせてワーカーを立て直し、常駐アプリは動き続ける（異常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    begin_recording(app, paste_target)
    speak_and_confirm(app)

    # 実行
    kills = kill_workers_twice(app)

    # 検証
    assert kills >= 2
    assert wait_until(lambda: app.notified("transcription_failed"), 120)
    wait_processed(app)
    assert app.service.is_running()
    assert paste_target.text() == ""
    assert len(app.service.history_files(".wav")) == 1
    assert wait_until(lambda: len(app.worker_processes()) > 0, 120)


def test_error_when_transcription_failed(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """文字起こしに失敗すると、失敗を知らせて何も届けず、録音は履歴に残る（異常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY + FAILING_ENGINE_SETTINGS)
    begin_recording(app, paste_target)

    # 実行
    speak_and_confirm(app)

    # 検証
    assert wait_until(lambda: app.notified("transcription_failed"), 120)
    wait_processed(app)
    assert paste_target.text() == ""
    assert pyperclip.paste() == clipboard_sentinel
    assert len(app.service.history_files(".wav")) == 1


def test_error_when_transcription_empty(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """起こした文字が空なら、何も届けず、録音は履歴に残る（異常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY + NO_SPEECH_SETTINGS)
    begin_recording(app, paste_target)

    # 実行（何も話さずに録音を続けて確定する）
    wait_until(lambda: False, RECORD_SEC)
    app.press("output_button_paste_and_send")

    # 検証
    assert app.wait_window_gone("recording_window")
    wait_processed(app)
    assert paste_target.text() == ""
    assert paste_target.enters() == 0
    assert pyperclip.paste() == clipboard_sentinel
    assert len(app.service.history_files(".wav")) == 1


def test_normal_when_api_empty(start_app: StartApp, receiver: CallbackReceiver) -> None:
    """API から始めた録音の結果が空でも、空の文字が返送先に 1 回届く（正常シナリオ）。"""
    # 準備
    app = start_app(NO_SPEECH_SETTINGS)

    # 実行
    session_id, payload = record_via_api(app, receiver)

    # 検証
    assert payload == {"session_id": session_id, "result": "transcribed", "text": "", "error": None}
    assert len(app.service.history_files(".wav")) == 1


def test_error_when_api_failed(start_app: StartApp, receiver: CallbackReceiver) -> None:
    """API から始めた録音の文字起こしに失敗すると、失敗が返送先に 1 回届き、常駐アプリは動き続ける（異常シナリオ）。"""
    # 準備
    app = start_app(FAILING_ENGINE_SETTINGS)

    # 実行
    session_id, payload = record_via_api(app, receiver)

    # 検証
    assert payload["session_id"] == session_id
    assert payload["result"] == "failed"
    assert payload["text"] == ""
    assert "xx" in payload["error"]
    assert len(app.service.history_files(".wav")) == 1
    assert app.service.is_running()


def test_error_when_notification_clicked_in_center(
    start_app: StartApp, paste_target: PasteTarget, explorer_to_close: list[Path]
) -> None:
    """通知センターに残った失敗の通知を押すと、ログフォルダが開く（異常シナリオ）。"""
    # 準備（文字起こしに失敗させて通知を出し、通知が畳まれて通知センターに残るのを待つ）
    app = start_app(PASTE_AND_SEND_ONLY + FAILING_ENGINE_SETTINGS)
    log_dir: Path = app.service.data_dir / "log"
    explorer_to_close.append(log_dir)
    begin_recording(app, paste_target)
    speak_and_confirm(app)
    assert wait_until(lambda: app.notified("transcription_failed"), 120)
    wait_processed(app)
    wait_until(lambda: False, 8)

    # 実行
    open_notification_center()
    notification = app.uia.find_by_name(NOTIFICATION_TITLE, timeout_sec=WINDOW_TIMEOUT_SEC)
    assert notification is not None, "通知センターに失敗の通知が残っていない"
    app.uia.click_center(notification)

    # 検証
    assert wait_until(lambda: log_dir in explorer_locations(), 20), "ログフォルダが開かなかった"
    assert app.tray_state() == IDLE
