"""連続録音のセッションの上限時間（continuous_session_limit）の非機能要件テスト。

録音の入力を 1 秒ほどの話し声の後に無音が続く WAV を実時間で流すもの、システム音量を何もしないものに差し替えた録音機
（実機のマイクを開かず、GPU を使わない。話し声の判定は本物、文字起こしは決まった文字を返すもの）で、連続録音の上限時間を
短い値に差し替えた SessionManager を上限のタイマーで回し、完了を呼ばないまま打ち切られて、返送先へ区間の文字と、
truncated と区間の数が届くことを確かめる。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.fixtures import receiver  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import (
    SPEECH_TEXT,
    InProcessApi,
    serve_api,
    speech_sequence_input,
)
from tests.support.light_session import build_light_manager
from voice_paste.features.outputs.callback.service import is_callback_allowed
from voice_paste.features.session import SessionApiDeps, SessionManager
from voice_paste.main import API_SESSION_LIMIT_SEC, SESSION_LIMIT_CHECK_INTERVAL_SEC
from voice_paste.runtime.timer import RepeatingTimer
from voice_paste.shared.types import ProgressFn

pytestmark = pytest.mark.real_machine

SHORT_LIMIT_SEC = 3.0
"""テストで待てる短い連続録音の上限時間（決定値 14400 秒の代わり）。"""

SEGMENT_CALLBACK_LATENCY_SEC = 4.0
"""区切ってから返送が届くまでの時間の決定値。上限での打ち切りの遅れに足す。"""

TAIL_SILENCE_SEC = 10.0
"""話し声を流し終えた後に流し続ける無音の長さ（上限時間と打ち切りの遅れより長くする）。"""

RECEIVE_TIMEOUT_SEC = SHORT_LIMIT_SEC + SESSION_LIMIT_CHECK_INTERVAL_SEC + 10.0
"""開始から終わりの返送が届くまで待つ上限。"""

SPEECH_STUB_TEXT = "テスト"
"""文字起こしの代わりが返す文字。"""


def _stub_transcribe(_audio_path: Path, _on_progress: ProgressFn | None) -> str:
    """GPU を使わないため、区間の録音を起こさずに決まった文字を返す。"""
    return SPEECH_STUB_TEXT


@pytest.fixture
def session(
    tmp_path: Path, receiver: CallbackReceiver  # noqa: F811
) -> Iterator[tuple[SessionManager, InProcessApi]]:
    """連続録音の上限時間を短くした SessionManager と、それを叩く API を作り、上限のタイマーを回す。"""
    wav_input = speech_sequence_input(
        tmp_path, [SPEECH_TEXT], gap_sec=0.0, tail_silence_sec=TAIL_SILENCE_SEC
    )
    manager = build_light_manager(
        tmp_path,
        wav_input,
        session_limit_sec=API_SESSION_LIMIT_SEC,
        continuous_session_limit_sec=SHORT_LIMIT_SEC,
        transcribe_fn=_stub_transcribe,
    )
    api = serve_api(
        SessionApiDeps(
            session_manager=manager,
            is_callback_allowed=partial(is_callback_allowed, allowed_hosts=frozenset()),
        )
    )
    timer = RepeatingTimer(manager.truncate_if_expired, SESSION_LIMIT_CHECK_INTERVAL_SEC)
    timer.start()
    yield manager, api
    timer.stop()
    api.close()
    manager.close()


def test_continuous_session_limit(
    session: tuple[SessionManager, InProcessApi], receiver: CallbackReceiver  # noqa: F811
) -> None:
    """完了が来ないまま上限時間に達した連続録音が打ち切られ、返送先へ truncated と区間の数が届く（実機）。"""
    # 準備
    manager, api = session
    started_at = time.monotonic()

    # 実行: 連続録音を始め、完了を呼ばずに上限を待つ
    response, _elapsed_ms = api.start_session(receiver.url, continuous=True)
    assert response.status_code == 202
    assert wait_until(
        lambda: any(payload["segment_number"] is None for payload in receiver.received),
        RECEIVE_TIMEOUT_SEC,
    )
    elapsed = time.monotonic() - started_at

    # 検証
    print(  # noqa: T201 測った値を実行の出力に残す
        f"continuous_session_limit: elapsed={elapsed:.2f}s "
        f"results={[(p['result'], p['segment_number'], p['segment_count']) for p in receiver.received]}"
    )
    upper = SHORT_LIMIT_SEC + SESSION_LIMIT_CHECK_INTERVAL_SEC + SEGMENT_CALLBACK_LATENCY_SEC
    assert SHORT_LIMIT_SEC <= elapsed <= upper
    [segment, end] = receiver.received
    assert segment["segment_number"] == 1
    assert segment["result"] == "transcribed"
    assert end["result"] == "truncated"
    assert end["segment_count"] == 1
    # 続けて呼んだ開始が 202 になる
    assert wait_until(lambda: manager.current() is None)
    assert api.start_session(receiver.url)[0].status_code == 202
