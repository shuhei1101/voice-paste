"""複合ユースケース「声で入力した文字を貼り付ける」の E2E テスト。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、ホットキーの入口（`start_local_session`）から録音を始める
（起動・トレイ・ホットキーの受付は通さない）。録音の入力は、音声合成（Windows は SAPI、Linux は Open JTalk）で決めた文を書き出した WAV を流す
ものに差し替え、マイクもスピーカーも通さない。システム音量・貼り付けのキー・通知は差し替えて、呼ばれた値を控える。
文字起こしはローカルの Whisper（Windows は GPU、Linux は CPU）、クリップボードは実物を使う（テストの後に元の文字へ戻す）。
実機の Windows と GPU か、Ubuntu 24.04 の Xorg のセッションが要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pyperclip
import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.inprocess import (
    SPEECH_WORD,
    LOWERS_VOLUME,
    expected_lowered_ratios,
    expected_restored_volumes,
    WORKER_CLIENT_LOGGER,
    InProcessApp,
    break_saved_recordings,
    kill_workers_twice,
    make_settings,
    silence_input,
    speech_input,
    worker_process_pids,
    worker_processes,
    worker_ready_messages,
)
from voice_paste.features.session.types import SessionState
from voice_paste.shared.types import Entry

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]

WORKER_RESTART_TIMEOUT_SEC = 120.0
"""やり直したワーカーも異常終了した後、文字起こしワーカーが立て直されるまで待つ上限。"""

PASTE_AND_SEND = "paste_and_send"
"""確定に選ぶ出力先の ID（貼り付けて送信）。"""

LONG_SPEECH_REPEAT = 10
"""ワーカーを止める間に起こし終わらないよう、読み上げた音をつなげる回数。"""

LOWERED_RATIO = 0.5
"""設定の既定（録音中の音量 50%）で、録音前の音量に掛けて下げる割合。"""


def _assert_can_start_again(app: InProcessApp) -> None:
    """ホットキーの入口からもう一度録音を始められることを確かめ、取り消して待機中へ戻す。"""
    app.start_hotkey()
    session = app.manager.current()
    assert session is not None
    assert session.entry == Entry.HOTKEY
    assert session.state == SessionState.RECORDING
    app.manager.cancel()
    assert app.manager.current() is None


def test_normal(
    start_inprocess: StartInProcess, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """録音して起こした文字が、クリップボードに入り、貼り付けと Enter が送信される（正常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=speech_input(tmp_path)
    )

    # 実行
    app.start_hotkey()
    app.manager.complete(output_id=PASTE_AND_SEND)

    # 検証
    assert app.wait_idle()
    assert app.volume.lowered_ratios == expected_lowered_ratios(LOWERED_RATIO)
    assert len(app.keys.pasted) == 1
    assert app.keys.enters == 1
    assert SPEECH_WORD in pyperclip.paste()
    [recording] = app.history_files(".wav")
    [text_file] = app.history_files(".txt")
    assert recording.stem == text_file.stem
    assert text_file.read_text(encoding="utf-8") == pyperclip.paste()
    assert app.volume.restored == expected_restored_volumes()
    _assert_can_start_again(app)


def test_normal_when_cancel(
    start_inprocess: StartInProcess, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """録音を確定せずに取り消すと、何も届けずに待機中へ戻る（正常シナリオ）。"""
    # 準備
    app = start_inprocess(settings=make_settings(), wav_input=speech_input(tmp_path))
    app.start_hotkey()
    assert (app.volume.lowered_ratios != []) == LOWERS_VOLUME

    # 実行
    app.manager.cancel()

    # 検証
    assert app.manager.current() is None
    assert pyperclip.paste() == clipboard_sentinel
    assert app.keys.pasted == []
    assert app.history_files(".wav") == []
    assert app.volume.restored == expected_restored_volumes()
    _assert_can_start_again(app)


def test_error_when_transcription_failed(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """中身の壊れた録音を確定すると、文字起こしの失敗を知らせて貼り付けず、録音は履歴に残る（異常シナリオ）。"""
    # 準備
    break_saved_recordings(monkeypatch)
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True), wav_input=speech_input(tmp_path)
    )
    app.start_hotkey()

    # 実行
    app.manager.complete(output_id=PASTE_AND_SEND)

    # 検証
    assert app.wait_idle()
    assert app.notifications.has("transcription_failed")
    assert app.keys.pasted == []
    assert pyperclip.paste() == clipboard_sentinel
    assert len(app.history_files(".wav")) == 1
    _assert_can_start_again(app)


def test_error_when_worker_dies_again(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    clipboard_sentinel: str,
) -> None:
    """文字起こしワーカーが落ち、やり直したワーカーも落ちると、失敗を知らせてワーカーを立て直す（異常シナリオ）。"""
    # 準備
    caplog.set_level(logging.INFO, logger=WORKER_CLIENT_LOGGER)
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True),
        wav_input=speech_input(tmp_path, repeat=LONG_SPEECH_REPEAT),
    )
    app.start_hotkey()
    # 止めるワーカーの番号は、確定の前に引いておく
    workers_before = worker_process_pids()
    app.manager.complete(output_id=PASTE_AND_SEND)

    # 実行
    kills = kill_workers_twice(workers_before, lambda: worker_ready_messages(caplog))

    # 検証
    assert kills >= 2
    assert app.wait_idle()
    assert app.notifications.has("transcription_failed")
    assert app.keys.pasted == []
    assert pyperclip.paste() == clipboard_sentinel
    assert len(app.history_files(".wav")) == 1
    assert wait_until(lambda: len(worker_processes()) > 0, WORKER_RESTART_TIMEOUT_SEC), (
        "文字起こしワーカーが立て直されなかった"
    )
    _assert_can_start_again(app)


def test_error_when_transcription_empty(
    start_inprocess: StartInProcess, tmp_path: Path, clipboard_sentinel: str
) -> None:
    """起こした文字が空なら、何も届けず、録音は履歴に残る（異常シナリオ）。"""
    # 準備
    app = start_inprocess(
        settings=make_settings(only_paste_and_send=True, vad_threshold=1.0),
        wav_input=silence_input(tmp_path),
    )
    app.start_hotkey()

    # 実行
    app.manager.complete(output_id=PASTE_AND_SEND)

    # 検証
    assert app.wait_idle()
    assert app.keys.pasted == []
    assert app.keys.enters == 0
    assert pyperclip.paste() == clipboard_sentinel
    assert len(app.history_files(".wav")) == 1
    _assert_can_start_again(app)


def test_error_when_api_session_busy(
    start_inprocess: StartInProcess, tmp_path: Path, receiver: CallbackReceiver
) -> None:
    """API の録音の処理中にホットキーの入口から録音を始めると、処理中を知らせ、API の録音は続く（異常シナリオ）。"""
    # 準備
    app = start_inprocess(settings=make_settings(), wav_input=speech_input(tmp_path))
    api = app.start_api()
    response, _elapsed_ms = api.start_session(receiver.url)
    assert response.status_code == 202

    # 実行
    app.start_hotkey()

    # 検証
    assert app.notifications.has("busy")
    assert app.wav_input.open_count == 1
    session = app.manager.current()
    assert session is not None
    assert session.entry == Entry.API
    assert session.state == SessionState.RECORDING
