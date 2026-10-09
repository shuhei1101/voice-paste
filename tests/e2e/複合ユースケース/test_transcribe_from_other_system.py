"""複合ユースケース「ほかのシステムから録音を文字に起こす」の E2E テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、API は `build_fastapi` で組み立てた app を 127.0.0.1 で待ち受けさせて叩く。
返送先は 127.0.0.1 でテストが立てる受け口。録音の入力は、Windows の音声合成（SAPI）で決めた文を書き出した WAV を流すものに
差し替え、マイクもスピーカーも通さない。貼り付けのキーは差し替えて、送られないことを確かめる。
文字起こしはローカルの Whisper（GPU）、クリップボードは実物を使う（テストの後に元の文字へ戻す）。
実機の Windows と GPU が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.inprocess import (
    SPEECH_WORD,
    InProcessApi,
    InProcessApp,
    break_saved_recordings,
    make_settings,
    silence_input,
    speech_input,
)
from voice_paste.features.session.types import SessionState
from voice_paste.shared.types import Entry

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]

RECEIVE_TIMEOUT_SEC = 60.0
"""完了から返送が届くまで待つ上限。"""

QUIET_SEC = 1.5
"""返送が 1 回届いた後、2 回目が届かないことを確かめるために待つ秒数。"""


def _record_and_complete(
    api: InProcessApi, receiver: CallbackReceiver
) -> tuple[str, dict[str, Any]]:
    """API で開始・停止・完了を呼び、返送が 1 回だけ届くのを待って、セッションの ID と届いた中身を返す。"""
    response, _elapsed_ms = api.start_session(receiver.url)
    assert response.status_code == 202
    session_id = str(response.json()["session_id"])
    assert api.post(f"/sessions/{session_id}/stop").status_code == 200
    assert api.post(f"/sessions/{session_id}/complete").status_code == 202
    assert wait_until(lambda: len(receiver.received) >= 1, RECEIVE_TIMEOUT_SEC)
    time.sleep(QUIET_SEC)
    assert len(receiver.received) == 1
    return session_id, receiver.received[0]


def _assert_can_start_again(api: InProcessApi, app: InProcessApp, receiver: CallbackReceiver) -> None:
    """続けて API の開始を呼ぶと次の録音を始められることを確かめる。"""
    assert app.wait_idle()
    assert api.start_session(receiver.url)[0].status_code == 202


def test_normal(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    receiver: CallbackReceiver,
    clipboard_sentinel: str,
) -> None:
    """ほかのプロセスが API で録音し、返送先に起こした文字が 1 回届く（正常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=speech_input(tmp_path)
    )
    api = app.start_api()

    # 実行
    session_id, payload = _record_and_complete(api, receiver)

    # 検証
    assert payload["session_id"] == session_id
    assert payload["result"] == "transcribed"
    assert payload["error"] is None
    assert SPEECH_WORD in payload["text"]
    # 履歴に録音と起こした文字が残り、文字は返送した中身と一致する
    [recording] = app.history_files(".wav")
    [text_file] = app.history_files(".txt")
    assert session_id in recording.name
    assert text_file.read_text(encoding="utf-8") == payload["text"]
    # API からの録音で貼り付けが起きない（クリップボードが録音前のまま）
    assert pyperclip.paste() == clipboard_sentinel
    assert app.keys.pasted == []
    assert app.keys.enters == 0
    _assert_can_start_again(api, app, receiver)


def test_normal_when_transcription_empty(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """起こした文字が空でも、空の文字が返送先に 1 回届く（正常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(vad_threshold=1.0), wav_input=silence_input(tmp_path)
    )
    api = app.start_api()

    # 実行
    session_id, payload = _record_and_complete(api, receiver)

    # 検証
    assert payload == {
        "session_id": session_id,
        "result": "transcribed",
        "text": "",
        "error": None,
    }
    [recording] = app.history_files(".wav")
    assert session_id in recording.name
    _assert_can_start_again(api, app, receiver)


def test_error_when_transcription_failed(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receiver: CallbackReceiver,
) -> None:
    """文字起こしに失敗したことが返送先に 1 回届き、サービスは動き続ける（異常シナリオ）。"""
    # 準備
    break_saved_recordings(monkeypatch)
    app = start_inprocess(settings=make_settings(), wav_input=speech_input(tmp_path))
    api = app.start_api()

    # 実行
    session_id, payload = _record_and_complete(api, receiver)

    # 検証
    assert payload["session_id"] == session_id
    assert payload["result"] == "failed"
    assert payload["text"] == ""
    assert payload["error"]
    [recording] = app.history_files(".wav")
    assert session_id in recording.name
    _assert_can_start_again(api, app, receiver)


def test_error_when_hotkey_recording(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """ホットキーの録音中に API の開始を呼ぶと 409 で断られ、その録音は続く（異常シナリオ）。"""
    # 準備
    app = start_inprocess(settings=make_settings(), wav_input=speech_input(tmp_path))
    api = app.start_api()
    app.start_hotkey()

    # 実行
    response, _elapsed_ms = api.start_session(receiver.url)

    # 検証
    assert response.status_code == 409
    assert app.wav_input.open_count == 1
    session = app.manager.current()
    assert session is not None
    assert session.entry == Entry.HOTKEY
    assert session.state == SessionState.RECORDING
    assert receiver.received == []
