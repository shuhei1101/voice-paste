"""features/session の単体テスト用の偽物と組み立て。

SessionDeps の関数は呼び出しを覚える Mock に、時刻は進められる時計に、
ワーカースレッドは「起動を覚えるだけで、テストが好きなときに動かす」偽物に差し替える。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from unittest.mock import MagicMock

import numpy as np
import pytest

if TYPE_CHECKING:
    from voice_paste.features.session.service import SessionManager
    from voice_paste.features.session.types import Session
    from voice_paste.shared.types import Segment, TranscriptionOutcome

SAMPLE_RATE = 16000
START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LIMIT = timedelta(seconds=600)
CONTINUOUS_LIMIT = timedelta(seconds=3600)
CALLBACK_URL = "http://127.0.0.1:9000/result"
WAIT_SEC = 3.0
POLL_SEC = 0.01


class Clock:
    """進められる今の時刻。SessionDeps の now に渡す。"""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        """今の時刻を返す。"""
        return self.current


class DeferredThread:
    """threading.Thread の偽物。start で起動を覚えるだけで、run_now を呼ぶまで動かさない。"""

    def __init__(
        self,
        group: None = None,
        target: Callable[..., object] | None = None,
        name: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.started = False

    def start(self) -> None:
        """起動したことを覚える（target は動かさない）。"""
        self.started = True

    def join(self, timeout: float | None = None) -> None:
        """終わりを待つ代わりに何もしない。"""

    def is_alive(self) -> bool:
        """動いていないものとして False を返す。"""
        return False

    def run_now(self) -> None:
        """覚えた target をその場で動かす。"""
        assert self._target is not None
        self._target(*self._args, **self._kwargs)


def defer_workers(monkeypatch: pytest.MonkeyPatch) -> list[DeferredThread]:
    """threading.Thread を DeferredThread に差し替え、start された偽物のスレッドを起動順に並べたリストを返す。"""
    started: list[DeferredThread] = []

    class _RecordingThread(DeferredThread):
        def start(self) -> None:
            super().start()
            started.append(self)

    monkeypatch.setattr(threading, "Thread", _RecordingThread)
    return started


@dataclass
class Harness:
    """SessionManager と、注入した偽物。"""

    manager: SessionManager
    clock: Clock
    audio_path: Path
    parent: MagicMock
    start_recording: MagicMock
    pause_recording: MagicMock
    resume_recording: MagicMock
    stop_recording: MagicMock
    discard_recording: MagicMock
    save_recording: MagicMock
    transcribe: MagicMock
    correct: MagicMock
    append_text: MagicMock
    deliver: MagicMock
    notify: MagicMock
    discard_temporary: MagicMock
    start_continuous_recording: MagicMock
    stop_continuous_recording: MagicMock

    def call_names(self) -> list[str]:
        """SessionDeps の関数が呼ばれた順に、関数の名前を返す。"""
        return [name for name, _, _ in self.parent.mock_calls]

    def events(self) -> list[str]:
        """notify に渡された知らせの種類を、渡された順に返す。"""
        return [call.args[0] for call in self.notify.call_args_list]

    def delivered(self) -> TranscriptionOutcome:
        """deliver に最後に渡された結果を返す。"""
        return self.deliver.call_args.args[1]

    def on_segment(self) -> Callable[[Segment], None]:
        """start_continuous_recording に渡された、区間の渡し先を返す。"""
        return self.start_continuous_recording.call_args.args[0]  # type: ignore[no-any-return]

    def on_failed(self) -> Callable[[str], None]:
        """start_continuous_recording に渡された、区切りの失敗の知らせ先を返す。"""
        return self.start_continuous_recording.call_args.args[1]  # type: ignore[no-any-return]

    def outcome_rows(self) -> list[tuple[str, int | None, int | None]]:
        """deliver に渡された結果を渡された順に、(result, segment_number, segment_count) の並びで返す。"""
        return [
            (outcome.result, outcome.segment_number, outcome.segment_count)
            for outcome in (call.args[1] for call in self.deliver.call_args_list)
        ]

    def saved_segment_numbers(self) -> list[int | None]:
        """save_recording に渡された区間の通し番号を、渡された順に返す（位置引数でもキーワード引数でも読む）。"""
        return [
            call.args[2] if len(call.args) > 2 else call.kwargs.get("segment_number")
            for call in self.save_recording.call_args_list
        ]

    def wait_for(self, condition: Callable[[], bool], timeout: float = WAIT_SEC) -> bool:
        """condition が真になるのを timeout 秒まで待ち、真になったかを返す。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(POLL_SEC)
        return condition()

    def wait_until_idle(self, timeout: float = WAIT_SEC) -> bool:
        """セッションが空（待機中）になるのを timeout 秒まで待ち、空になったかを返す。"""
        return self.wait_for(lambda: self.manager.current() is None, timeout)

    def current(self) -> Session:
        """今のセッションを返す（無ければ失敗させる）。"""
        session = self.manager._session
        assert session is not None
        return session

    def state(self) -> str | None:
        """今のセッションの状態を返す。セッションが無ければ None。"""
        session = self.manager._session
        return None if session is None else str(session.state)


def make_harness(audio_path: Path, *, report_progress: MagicMock | None = None) -> Harness:
    """全ての依存を Mock にした SessionManager を作る。録音の保存先は audio_path。

    report_progress は SessionDeps の report_progress（文字起こしの進みの知らせ）。渡さなければ Mock にする。
    """
    from voice_paste.features.session.service import SessionManager
    from voice_paste.features.session.types import SessionDeps
    from voice_paste.shared.types import Recording

    clock = Clock(START)
    recording = Recording(
        samples=np.zeros(SAMPLE_RATE, dtype=np.int16),
        sample_rate=SAMPLE_RATE,
        duration_sec=1.0,
    )
    mocks = {
        "start_recording": MagicMock(return_value=None),
        "pause_recording": MagicMock(return_value=None),
        "resume_recording": MagicMock(return_value=None),
        "stop_recording": MagicMock(return_value=recording),
        "discard_recording": MagicMock(return_value=None),
        "save_recording": MagicMock(return_value=audio_path),
        "transcribe": MagicMock(return_value="てすと"),
        "correct": MagicMock(side_effect=lambda text: text),
        "append_text": MagicMock(return_value=None),
        "deliver": MagicMock(return_value=None),
        "notify": MagicMock(return_value=None),
        "discard_temporary": MagicMock(return_value=None),
        "start_continuous_recording": MagicMock(return_value=None),
        "stop_continuous_recording": MagicMock(return_value=None),
    }
    # 呼ばれた順を 1 本の列で見られるよう、1 つの親にぶら下げる
    parent = MagicMock()
    for name, mock in mocks.items():
        parent.attach_mock(mock, name)

    deps = SessionDeps(
        now=clock,
        report_progress=MagicMock() if report_progress is None else report_progress,
        **mocks,
    )
    return Harness(
        manager=SessionManager(
            deps, session_limit=LIMIT, continuous_session_limit=CONTINUOUS_LIMIT
        ),
        clock=clock,
        audio_path=audio_path,
        parent=parent,
        **mocks,
    )


def make_segment(reason: Literal["silence", "max_length", "flush"] = "silence") -> Segment:
    """連続録音の区間（1 秒の無音の音）を作る。"""
    from voice_paste.shared.types import Recording, Segment

    recording = Recording(
        samples=np.zeros(SAMPLE_RATE, dtype=np.int16),
        sample_rate=SAMPLE_RATE,
        duration_sec=1.0,
    )
    return Segment(recording=recording, reason=reason)
