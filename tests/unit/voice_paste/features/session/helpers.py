"""features/session の単体テスト用の偽物と組み立て。

SessionDeps の関数は呼び出しを覚える Mock に、時刻は進められる時計に、
ワーカースレッドは「起動を覚えるだけで、テストが好きなときに動かす」偽物に差し替える。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import numpy as np
import pytest

if TYPE_CHECKING:
    from voice_paste.features.session.service import SessionManager
    from voice_paste.features.session.types import Session
    from voice_paste.shared.types import TranscriptionOutcome

SAMPLE_RATE = 16000
START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
LIMIT = timedelta(seconds=600)
CALLBACK_URL = "http://127.0.0.1:9000/result"


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

    def call_names(self) -> list[str]:
        """SessionDeps の関数が呼ばれた順に、関数の名前を返す。"""
        return [name for name, _, _ in self.parent.mock_calls]

    def events(self) -> list[str]:
        """notify に渡された知らせの種類を、渡された順に返す。"""
        return [call.args[0] for call in self.notify.call_args_list]

    def delivered(self) -> TranscriptionOutcome:
        """deliver に最後に渡された結果を返す。"""
        return self.deliver.call_args.args[1]

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

    report_progress を渡したときだけ、SessionDeps の report_progress（文字起こしの進みの知らせ）に渡す。
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
    }
    # 呼ばれた順を 1 本の列で見られるよう、1 つの親にぶら下げる
    parent = MagicMock()
    for name, mock in mocks.items():
        parent.attach_mock(mock, name)

    progress_deps = {} if report_progress is None else {"report_progress": report_progress}
    deps = SessionDeps(now=clock, **mocks, **progress_deps)
    return Harness(
        manager=SessionManager(deps, session_limit=LIMIT),
        clock=clock,
        audio_path=audio_path,
        parent=parent,
        **mocks,
    )
