"""実機の E2E で共通の操作の流れ（録音を始める・話す・確定する・処理が終わるまで待つ）と設定。"""

from __future__ import annotations

import time
from typing import Any

from tests.integration.helpers import CallbackReceiver
from tests.support.app_driver import IDLE, STATE_TIMEOUT_SEC, AppDriver
from tests.support.desktop import PasteTarget, speak, wait_until

PASTE_AND_SEND_ONLY = '[[outputs]]\nid = "paste_and_send"\n'
"""出力先のうち「貼り付けて送信」だけをオンにする設定。"""

NO_SPEECH_SETTINGS = "[transcription.local_whisper]\nvad_threshold = 1.0\n"
"""どんな音も音声とみなさない設定（起こした文字が空になる）。"""

FAILING_ENGINE_SETTINGS = '[transcription.local_whisper]\nlanguage = "xx"\n'
"""存在しない言語コード（ワーカーが文字起こしでエラーを返し、起こすのに失敗する）。"""

SPEECH_TEXT = "これはテストです"
"""録音中にスピーカーから読み上げる文。マイクがその音を拾う前提で、起こした文字の中身は決め打ちしない。"""

PASTE_AND_SEND_BUTTON = "output_button_paste_and_send"
"""録音の画面の「貼り付けて送信」のボタンの項目 ID。"""

PASTE_TIMEOUT_SEC = 120.0
"""確定から貼り付け先に文字が入るまで待つ上限。"""

VOLUME_TOLERANCE = 0.03
"""音量が戻ったとみなす差。"""

RECORD_SEC = 2.0
"""話さずに録音を続ける秒数。"""


def begin_recording(app: AppDriver, paste: PasteTarget | None = None) -> str:
    """録音を始め、録音の画面が出たら貼り付け先を前面に戻す。始めた入口（hotkey か tray）を返す。"""
    entry = app.start_recording()
    app.wait_window("recording_window")
    if paste is not None:
        paste.focus()
    return entry


def speak_and_confirm(
    app: AppDriver, *, output: str = PASTE_AND_SEND_BUTTON, text: str = SPEECH_TEXT
) -> None:
    """録音中に text を読み上げ、録音の画面の出力先のボタンで確定する。"""
    speak(text)
    app.press(output)


def wait_processed(app: AppDriver, timeout_sec: float = STATE_TIMEOUT_SEC) -> None:
    """確定した録音の処理（文字起こし・届ける）が終わり、トレイが待機中に戻るまで待つ。"""
    app.wait_tray_state(IDLE, timeout_sec)


def wait_pasted(paste: PasteTarget, timeout_sec: float = PASTE_TIMEOUT_SEC) -> bool:
    """貼り付け先に文字が入り、Enter が 1 回送られるまで待ち、入ったかを返す。"""
    return wait_until(lambda: paste.text() != "" and paste.enters() >= 1, timeout_sec)


def wait_volume_restored(volume_before: float, timeout_sec: float = 15.0) -> bool:
    """システム音量が録音前の値に戻るまで待ち、戻ったかを返す。"""
    from tests.support.desktop import master_volume

    return wait_until(lambda: abs(master_volume() - volume_before) < VOLUME_TOLERANCE, timeout_sec)


def wait_volume_lowered(volume_before: float, timeout_sec: float = 15.0) -> bool:
    """システム音量が録音前より下がるまで待ち、下がったかを返す（録音前が小さければ確かめない）。"""
    from tests.support.desktop import master_volume

    if volume_before < 0.1:
        return True
    return wait_until(lambda: master_volume() < volume_before - 0.05, timeout_sec)


def kill_workers_twice(app: AppDriver, timeout_sec: float = 90.0) -> int:
    """文字起こしワーカーを止め、やり直しに立ったワーカーも止める。止めた回数を返す。"""
    kills = 0
    deadline = time.monotonic() + timeout_sec
    while kills < 2 and time.monotonic() < deadline:
        kills += app.kill_workers()
        time.sleep(0.2)
    return kills


API_RECEIVE_TIMEOUT_SEC = 60.0
"""API の完了から返送が届くまで待つ上限。"""

API_QUIET_SEC = 1.5
"""返送が 1 回届いた後、2 回目が届かないことを確かめるために待つ秒数。"""


def record_via_api(app: AppDriver, receiver: CallbackReceiver) -> tuple[str, dict[str, Any]]:
    """API で開始・停止・完了を呼び、返送が 1 回だけ届くのを待って、セッションの ID と届いた中身を返す。"""
    service = app.service
    response, _elapsed_ms = service.start_session(receiver.url)
    assert response.status_code == 202
    session_id = str(response.json()["session_id"])
    time.sleep(RECORD_SEC)
    assert service.post(f"/sessions/{session_id}/stop").status_code == 200
    assert service.post(f"/sessions/{session_id}/complete").status_code == 202
    assert wait_until(lambda: len(receiver.received) >= 1, API_RECEIVE_TIMEOUT_SEC)
    time.sleep(API_QUIET_SEC)
    assert len(receiver.received) == 1
    return session_id, receiver.received[0]
