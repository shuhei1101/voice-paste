"""区切ってから返送が届くまでの時間（segment_callback_latency）の非機能要件テスト。

build_handlers で配線した常駐サービスをローカルの Whisper（GPU）で立て、録音の入力だけを、Windows の音声合成（SAPI）で作った
5 文（文の間に区切りの無音の長さより長い間を挟む）の後に 45 秒以上読み上げ続ける WAV を実時間で流すものに差し替える。
連続録音を始めて流し終えたら完了を呼び、区切った時点（Segmenter のログ）から、同じ通し番号の返送が受け口に届いた時点までを
区間ごとに測る。最初の区間はワーカーの温まりで遅れるため、測る前に別の連続録音で 1 区間を起こして温める。
`--run-e2e` が無ければ skip する。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.fixtures import receiver, start_inprocess  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import (
    SPEECH_TEXT,
    InProcessApp,
    complete_session,
    long_reading_texts,
    make_settings,
    speech_sequence_input,
    speech_timeline_input,
    start_continuous,
    wait_for_continuous_end,
)

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]

SEGMENT_CALLBACK_LATENCY_SEC = 3.0
"""区切ってから返送が届くまでの時間の決定値。"""

SEGMENTER_LOGGER = "voice_paste.features.recording.segmenter"
"""区切りの部品のロガーの名前。区間を区切るたびに INFO で書く。"""

CUT_LOG_PREFIX = "区間を区切った"
"""区間を区切ったときのログの文の先頭。"""

FLUSH_MARK = "（flush・"
"""完了で閉じた最後の区間のログに含まれる、区切った理由の印。"""

SEGMENT_GAP_SEC = 3.0
"""区切りの無音の長さの既定（2 秒）より長い、文と文の間の無音。"""

SHORT_GAP_SEC = 0.4
"""話し続ける読み上げの、文と文の間の無音。区切りの無音の長さの既定より短い。"""

SILENCE_SENTENCES = (
    SPEECH_TEXT,
    "今日はいい天気です",
    "ありがとうございました",
    "朝ごはんにパンを食べました",
    "図書館で本を借りました",
)
"""区切りの無音で区切る 5 文。"""

MIN_SEGMENTS = 7
"""区切りの無音で区切る 5 区間と、話し続けて最大の長さで区切る 2 区間以上。"""


class _ArrivalList(list[dict[str, Any]]):
    """返送先の受け口が届いた中身を足すとき、届いた時刻（time.perf_counter）も控える。"""

    def __init__(self) -> None:
        super().__init__()
        self.arrivals: list[float] = []

    def append(self, item: dict[str, Any]) -> None:
        """中身を足し、足した時刻を控える。"""
        self.arrivals.append(time.perf_counter())
        super().append(item)


class _CutLog(logging.Handler):
    """区切りの部品が区間を区切ったログの時刻（time.perf_counter）と文を控える。"""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.cuts: list[tuple[float, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        """区間を区切ったログなら、時刻と文を控える。"""
        message = record.getMessage()
        if message.startswith(CUT_LOG_PREFIX):
            self.cuts.append((time.perf_counter(), message))


@pytest.fixture
def cut_log() -> Iterator[_CutLog]:
    """区切りの部品のログを控えるハンドラーを付け、テストの後に外す。"""
    logger = logging.getLogger(SEGMENTER_LOGGER)
    previous_level = logger.level
    handler = _CutLog()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


def _measure_latencies(
    cut_log: _CutLog,
    receiver_list: _ArrivalList,
    offset: int,
    complete_called_at: float,
) -> list[tuple[int, float]]:
    """区間ごとに、区切った時点（完了で閉じた最後の区間は完了を呼んだ時点）から返送が届いた時点までを、(通し番号, 秒) で返す。"""
    arrived = [
        (payload["segment_number"], arrival)
        for payload, arrival in zip(
            receiver_list[offset:], receiver_list.arrivals[offset:], strict=True
        )
        if payload["segment_number"] is not None
    ]
    assert len(arrived) == len(cut_log.cuts)
    latencies: list[tuple[int, float]] = []
    for (number, arrival), (cut_at, message) in zip(arrived, cut_log.cuts, strict=True):
        # 完了で閉じた区間は、完了を呼んだ時点から測る
        start = complete_called_at if FLUSH_MARK in message else cut_at
        latencies.append((number, arrival - start))
    return latencies


def test_segment_callback_latency(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    receiver: CallbackReceiver,
    cut_log: _CutLog,
) -> None:
    """区切ってからその区間の返送が届くまでが、どの区間も決定値以内である（実機）。"""
    # 準備: 受け口が届いた時刻を控えるようにし、温めに 1 文だけを流す入力でサービスを立てる
    arrivals = _ArrivalList()
    receiver.received = arrivals
    app = start_inprocess(
        settings=make_settings(),
        wav_input=speech_sequence_input(tmp_path, [SPEECH_TEXT], gap_sec=SEGMENT_GAP_SEC),
    )
    api = app.start_api()

    # 温める: 別の連続録音で 1 区間を起こして、ワーカーを温める
    warm_session = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_session(api, warm_session)
    wait_for_continuous_end(receiver)
    assert app.wait_idle()
    offset = len(receiver.received)
    cut_log.cuts.clear()

    # 実行: 5 文の後に 45 秒以上読み上げ続ける入力に替えて連続録音を始め、流し終えたら完了を呼ぶ
    items = [(sentence, SEGMENT_GAP_SEC) for sentence in SILENCE_SENTENCES]
    # 話し続ける読み上げの最初の文だけ、前の文との間に区切りの無音の長さより長い間を挟み、後の文は短い間でつなぐ
    long_texts = long_reading_texts()
    items.append((long_texts[0], SEGMENT_GAP_SEC))
    items += [(sentence, SHORT_GAP_SEC) for sentence in long_texts[1:]]
    app.wav_input.samples = speech_timeline_input(tmp_path, items).samples
    session_id = start_continuous(api, receiver)
    assert app.wav_input.wait_played_out()
    complete_called_at = time.perf_counter()
    complete_session(api, session_id)
    wait_for_continuous_end(receiver, offset=offset)

    # 検証
    latencies = _measure_latencies(cut_log, arrivals, offset, complete_called_at)
    print(  # noqa: T201 測った値を実行の出力に残す
        "segment_callback_latency: "
        + " ".join(f"#{number}={seconds:.2f}s" for number, seconds in latencies)
    )
    assert len(latencies) >= MIN_SEGMENTS
    assert max(seconds for _number, seconds in latencies) <= SEGMENT_CALLBACK_LATENCY_SEC

