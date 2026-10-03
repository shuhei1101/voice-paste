"""複合ユースケース「ほかのシステムから録音を文字に起こす」の E2E テスト。

`python -m voice_paste --data-dir {一時フォルダ}` の本物の起動（build_handlers の配線・実機のマイク・ローカルの Whisper）を通し、
トークンのファイルを読んで API を叩く。返送先は 127.0.0.1 でテストが立てる受け口。
実機のマイクで録音し、システム音量を一時的に下げる（`--run-e2e` が無ければ skip する）。

起こした文字の中身は、実機のマイクが拾った音で決まる。そのため正常シナリオでは文字の中身を決め打ちせず、
返送の形と、履歴・クリップボードの扱いを確かめる。空と失敗は設定で決定的に作る。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.app_driver import RECORDING, AppDriver
from tests.support.flows import begin_recording
from tests.support.real_service import RealService

pytestmark = pytest.mark.real_machine

RECORD_SEC = 2.0
"""開始から停止までマイクで録る秒数。"""

RECEIVE_TIMEOUT_SEC = 60.0
"""完了から返送が届くまで待つ上限。"""

QUIET_SEC = 1.5
"""返送が 1 回届いた後、2 回目が届かないことを確かめるために待つ秒数。"""

EMPTY_RESULT_SETTINGS = "[transcription.local_whisper]\nvad_threshold = 1.0\n"
"""どんな音も音声とみなさない（無音の区間を除く設定で、起こした文字が空になる）。"""

FAILING_ENGINE_SETTINGS = '[transcription.local_whisper]\nlanguage = "xx"\n'
"""存在しない言語コード。ワーカーが文字起こしでエラーを返し、起こすのに失敗する。"""


def _record_and_complete(
    service: RealService, receiver: CallbackReceiver
) -> tuple[str, dict[str, Any]]:
    """API で開始・停止・完了を呼び、返送が 1 回だけ届くのを待って、セッションの ID と届いた中身を返す。"""
    response, _elapsed_ms = service.start_session(receiver.url)
    assert response.status_code == 202
    session_id = str(response.json()["session_id"])
    time.sleep(RECORD_SEC)
    assert service.post(f"/sessions/{session_id}/stop").status_code == 200
    assert service.post(f"/sessions/{session_id}/complete").status_code == 202
    assert wait_until(lambda: len(receiver.received) >= 1, RECEIVE_TIMEOUT_SEC)
    time.sleep(QUIET_SEC)
    assert len(receiver.received) == 1
    return session_id, receiver.received[0]


def test_normal(
    start_service: Callable[..., RealService],
    receiver: CallbackReceiver,
    clipboard_sentinel: str,
) -> None:
    """ほかのプロセスが API で録音し、返送先に起こした文字が 1 回届く（正常シナリオ）。"""
    # 準備
    service = start_service()

    # 実行
    session_id, payload = _record_and_complete(service, receiver)

    # 検証
    assert payload["session_id"] == session_id
    assert payload["result"] == "transcribed"
    assert payload["error"] is None
    assert isinstance(payload["text"], str)
    # 履歴に録音と起こした文字が残り、文字は返送した中身と一致する
    [recording] = service.history_files(".wav")
    [text_file] = service.history_files(".txt")
    assert session_id in recording.name
    assert text_file.read_text(encoding="utf-8") == payload["text"]
    # API からの録音で貼り付けが起きない（クリップボードが録音前のまま）
    assert pyperclip.paste() == clipboard_sentinel
    # 続けて開始を呼ぶと、次の録音を始められる
    assert service.is_running()
    assert service.start_session(receiver.url)[0].status_code == 202


def test_normal_when_transcription_empty(
    start_service: Callable[..., RealService], receiver: CallbackReceiver
) -> None:
    """起こした文字が空でも、空の文字が返送先に 1 回届く（正常シナリオ）。"""
    # 準備
    service = start_service(EMPTY_RESULT_SETTINGS)

    # 実行
    session_id, payload = _record_and_complete(service, receiver)

    # 検証
    assert payload == {
        "session_id": session_id,
        "result": "transcribed",
        "text": "",
        "error": None,
    }
    [recording] = service.history_files(".wav")
    assert session_id in recording.name
    assert service.is_running()
    assert service.start_session(receiver.url)[0].status_code == 202


def test_error_when_transcription_failed(
    start_service: Callable[..., RealService], receiver: CallbackReceiver
) -> None:
    """文字起こしに失敗したことが返送先に 1 回届き、サービスは動き続ける（異常シナリオ）。"""
    # 準備
    service = start_service(FAILING_ENGINE_SETTINGS)

    # 実行
    session_id, payload = _record_and_complete(service, receiver)

    # 検証
    assert payload["session_id"] == session_id
    assert payload["result"] == "failed"
    assert payload["text"] == ""
    assert "xx" in payload["error"]
    [recording] = service.history_files(".wav")
    assert session_id in recording.name
    assert service.is_running()
    assert service.start_session(receiver.url)[0].status_code == 202


def test_error_when_hotkey_recording(
    start_app: Callable[..., AppDriver], receiver: CallbackReceiver
) -> None:
    """ホットキー・トレイの録音中に API の開始を呼ぶと 409 で断られ、その録音は続く（異常シナリオ）。

    録音は、ホットキーで始める。
    """
    # 準備
    app = start_app()
    begin_recording(app)
    app.wait_tray_state(RECORDING)

    # 実行
    response, _elapsed_ms = app.service.start_session(receiver.url)

    # 検証
    assert response.status_code == 409
    assert app.tray_state() == RECORDING
    assert app.window("recording_window") is not None
    assert receiver.received == []
    app.press("cancel_button")
    assert app.wait_window_gone("recording_window")
