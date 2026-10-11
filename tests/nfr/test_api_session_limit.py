"""API のセッションの上限時間（api_session_limit）の非機能要件テスト。

録音の入力を無音の WAV を実時間で流すもの、システム音量を何もしないものに差し替えた録音機（実機のマイクを開かず、
GPU を使わない）で、上限時間を短い値に差し替えたセッションを、録音中と停止中の両方で打ち切り、返送先へ truncated が
届くことを確かめる。あわせて、履歴の WAV の大きさから 600 秒分の録音の大きさを求め、決定値の根拠（16 kHz・モノラル・
16 bit で 19.2 MB）と合うことを確かめる。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import time
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.fixtures import receiver  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import silence_input
from tests.support.light_session import build_light_manager
from voice_paste.features.session import SessionManager
from voice_paste.main import API_SESSION_LIMIT_SEC, SESSION_LIMIT_CHECK_INTERVAL_SEC
from voice_paste.runtime.timer import RepeatingTimer

pytestmark = pytest.mark.real_machine

SHORT_LIMIT_SEC = 3.0
"""テストで待てる短い上限時間（決定値 600 秒の代わり）。"""

SILENCE_SEC = 10.0
"""実時間で流す無音の WAV の長さ（上限時間と打ち切りの遅れより長くする）。"""

STOP_AFTER_SEC = 1.0
"""停止中の打ち切りで、開始から停止まで無音を流して録る秒数。"""

TRUNCATE_MARGIN_SEC = 3.0
"""打ち切りが上限時間から遅れてよい秒数（確かめる間隔と返送の分）。"""

RECEIVE_TIMEOUT_SEC = SHORT_LIMIT_SEC + TRUNCATE_MARGIN_SEC + 5.0
"""開始から返送が届くまで待つ上限。"""

WAV_SAMPLE_RATE = 16000
WAV_BYTES_PER_SAMPLE = 2
"""16 kHz・モノラル・16 bit の WAV の 1 秒あたりのバイト数の元。"""

EXPECTED_LIMIT_BYTES = 600 * WAV_SAMPLE_RATE * WAV_BYTES_PER_SAMPLE
"""600 秒の録音の大きさの根拠（19.2 MB）。"""

SIZE_TOLERANCE = 0.05
"""実機の WAV から求めた大きさが根拠の値とずれてよい割合。"""


@pytest.fixture
def manager(tmp_path: Path, receiver: CallbackReceiver) -> Iterator[SessionManager]:  # noqa: F811
    """入力を無音の WAV を実時間で流すもの・システム音量を何もしないものに差し替えた録音機で、上限時間を短くした SessionManager を作り、上限のタイマーを回す。"""
    session_manager = build_light_manager(
        tmp_path,
        silence_input(tmp_path, seconds=SILENCE_SEC, realtime=True),
        session_limit_sec=SHORT_LIMIT_SEC,
    )
    timer = RepeatingTimer(
        session_manager.truncate_if_expired, SESSION_LIMIT_CHECK_INTERVAL_SEC
    )
    timer.start()
    yield session_manager
    timer.stop()
    session_manager.close()


def _history_wavs(tmp_path: Path) -> list[Path]:
    """履歴に残った録音の WAV を返す。"""
    return sorted((tmp_path / "history").rglob("*.wav"))


def _wav_seconds_and_bytes(wav_path: Path) -> tuple[float, int]:
    """WAV の長さ（秒）とファイルの大きさ（バイト）を返す。"""
    with wave.open(str(wav_path), "rb") as wav:
        seconds = wav.getnframes() / wav.getframerate()
    return seconds, wav_path.stat().st_size


def _assert_truncated_in_time(
    receiver: CallbackReceiver, started_at: float, tmp_path: Path
) -> None:
    """上限時間の近くで返送先に truncated が届き、実機の録音から求めた 600 秒分の大きさが根拠と合うことを確かめる。"""
    assert wait_until(lambda: len(receiver.received) >= 1, RECEIVE_TIMEOUT_SEC)
    elapsed = time.monotonic() - started_at
    assert receiver.received[0]["result"] == "truncated"
    assert SHORT_LIMIT_SEC <= elapsed <= SHORT_LIMIT_SEC + TRUNCATE_MARGIN_SEC
    [wav_path] = _history_wavs(tmp_path)
    seconds, size = _wav_seconds_and_bytes(wav_path)
    projected = size / seconds * API_SESSION_LIMIT_SEC
    print(  # noqa: T201 測った値を実行の出力に残す
        f"api_session_limit: elapsed={elapsed:.2f}s wav={seconds:.2f}s {size}B "
        f"projected_600s={projected / 1_000_000:.2f}MB"
    )
    assert projected == pytest.approx(EXPECTED_LIMIT_BYTES, rel=SIZE_TOLERANCE)


def test_api_session_limit_when_recording(
    manager: SessionManager, receiver: CallbackReceiver, tmp_path: Path  # noqa: F811
) -> None:
    """録音中のまま上限時間に達したセッションが打ち切られ、返送先へ truncated が届く（実機）。"""
    # 準備
    started_at = time.monotonic()

    # 実行
    manager.start("api", callback_url=receiver.url)

    # 検証
    _assert_truncated_in_time(receiver, started_at, tmp_path)


def test_api_session_limit_when_stopped(
    manager: SessionManager, receiver: CallbackReceiver, tmp_path: Path  # noqa: F811
) -> None:
    """停止中のまま上限時間に達したセッションも打ち切られ、返送先へ truncated が届く（実機）。"""
    # 準備
    started_at = time.monotonic()
    session = manager.start("api", callback_url=receiver.url)
    time.sleep(STOP_AFTER_SEC)

    # 実行
    manager.stop(session.id)

    # 検証
    _assert_truncated_in_time(receiver, started_at, tmp_path)
