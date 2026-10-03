"""複合ユースケース「声で入力した文字を貼り付ける」の E2E テスト。

`python -m voice_paste --data-dir {一時フォルダ}` の本物の起動（Qt のイベントループ・トレイ・ホットキー・実機のマイク・
ローカルの Whisper）を通し、トレイ・録音の画面を UI Automation で操作して、貼り付け先（別プロセスの入力欄）へ届くまでを確かめる。
普段使いの `voice_paste_legacy` とリポジトリの直下の `.env`・`history/`・`log/` には触れない。

- 録音は、合成したキーでホットキーを押して始める（常駐アプリは環境変数 `VOICE_PASTE_ACCEPT_INJECTED_HOTKEYS=1` で起動し、合成したキーも受ける）
- 話す音は、スピーカーから読み上げた音をマイクが拾う前提（起こした文字の中身は決め打ちしない）
- 実機のマイクで録音し、システム音量を一時的に下げる（`--run-e2e` が無ければ skip する）
"""

from __future__ import annotations

from collections.abc import Callable

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.app_driver import IDLE, RECORDING, START_HOTKEY, AppDriver
from tests.support.desktop import (
    PasteTarget,
    master_volume,
    press_hotkey,
    wait_until,
)
from tests.support.flows import (
    FAILING_ENGINE_SETTINGS,
    NO_SPEECH_SETTINGS,
    PASTE_AND_SEND_ONLY,
    RECORD_SEC,
    begin_recording,
    kill_workers_twice,
    speak_and_confirm,
    wait_pasted,
    wait_processed,
    wait_volume_lowered,
    wait_volume_restored,
)

pytestmark = pytest.mark.real_machine

StartApp = Callable[..., AppDriver]


def _start_again_and_cancel(app: AppDriver) -> None:
    """続けて録音を始められることを確かめ、取り消して待機中へ戻す。"""
    begin_recording(app)
    app.press("cancel_button")
    assert app.wait_window_gone("recording_window")
    app.wait_tray_state(IDLE)


def test_normal(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """録音して起こした文字が、貼り付け先に貼り付けて送信される（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    volume_before = master_volume()

    # 実行
    begin_recording(app, paste_target)
    assert wait_volume_lowered(volume_before)
    speak_and_confirm(app)

    # 検証
    assert app.wait_window_gone("recording_window")
    assert wait_pasted(paste_target), "貼り付け先に文字が入らなかった（スピーカーの音をマイクが拾えない環境ではないか）"
    wait_processed(app)
    assert paste_target.enters() == 1
    assert pyperclip.paste() == paste_target.text()
    assert len(app.service.history_files(".wav")) == 1
    assert len(app.service.history_files(".txt")) == 1
    assert wait_volume_restored(volume_before)
    _start_again_and_cancel(app)


def test_normal_when_cancel(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """録音を確定せずに取り消すと、何も届けずに待機中へ戻る（正常シナリオ）。"""
    # 準備
    app = start_app(PASTE_AND_SEND_ONLY)
    volume_before = master_volume()
    begin_recording(app, paste_target)
    assert wait_volume_lowered(volume_before)

    # 実行
    app.press("cancel_button")

    # 検証
    assert app.wait_window_gone("recording_window")
    app.wait_tray_state(IDLE)
    assert pyperclip.paste() == clipboard_sentinel
    assert paste_target.text() == ""
    assert app.service.history_files(".wav") == []
    assert wait_volume_restored(volume_before)
    _start_again_and_cancel(app)


def test_error_when_transcription_failed(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """文字起こしに失敗すると、失敗を知らせて貼り付けず、録音は履歴に残る（異常シナリオ）。"""
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
    _start_again_and_cancel(app)


def test_error_when_worker_dies_again(
    start_app: StartApp, paste_target: PasteTarget, clipboard_sentinel: str
) -> None:
    """文字起こしワーカーが落ち、やり直したワーカーも落ちると、失敗を知らせてワーカーを立て直す（異常シナリオ）。"""
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
    assert wait_until(lambda: len(app.worker_processes()) > 0, 120), "文字起こしワーカーが立て直されなかった"


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
    _start_again_and_cancel(app)


def test_error_when_api_session_busy(
    start_app: StartApp, receiver: CallbackReceiver
) -> None:
    """API の録音の処理中に録音開始のホットキーを押すと、処理中のダイアログが出て API の録音は続く（異常シナリオ）。"""
    # 準備
    app = start_app()
    response, _elapsed_ms = app.service.start_session(receiver.url)
    assert response.status_code == 202
    app.wait_tray_state(RECORDING)

    # 実行
    press_hotkey(START_HOTKEY)

    # 検証
    app.wait_window("busy_dialog")
    texts = app.texts("busy_dialog")
    assert "録音を始められません" in texts
    assert app.tray_state() == RECORDING
    assert app.window("recording_window") is None
    app.press("close_button")
    assert app.wait_window_gone("busy_dialog")
    assert app.tray_state() == RECORDING
