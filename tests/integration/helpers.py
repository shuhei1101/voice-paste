"""結合テスト（常駐アプリの API とセッション）の偽物と組み立て。

本物の app（build_fastapi）を ApiServerRunner で 127.0.0.1 の空きポートに立て、httpx で叩く。
マイク・システム音量・文字起こしのエンジンは偽物にし、履歴は一時フォルダに書く。
返送先は、テストが 127.0.0.1 に立てる受け口にする。

ホットキー・トレイのセッションが確定で選んだ出力先へ届く結合テストは、API を立てず、
main.py の配線（_wire_outputs）で作った出力先を使い、キーボード・ブラウザのアダプタと間だけを偽物にする（build_output_stack）。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import numpy as np
import pytest

from voice_paste.features.correction import apply_glossary
from voice_paste.features.history import append_text, discard_temporary, save_recording
from voice_paste.features.outputs import OUTPUTS, deliver, is_callback_allowed
from voice_paste.features.outputs.callback.client import post_json
from voice_paste.features.outputs.registry import CALLBACK_OUTPUT_ID
from voice_paste.features.recording import Recorder
from voice_paste.features.session import (
    Session,
    SessionApiDeps,
    SessionDeps,
    SessionManager,
)
from voice_paste.features.transcription.service import transcribe
import voice_paste.main as main_module
from voice_paste.main import (
    CALLBACK_RETRY_COUNT,
    CALLBACK_TIMEOUT_SEC,
    _deliver_session,
    _wire_outputs,
)
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.settings import Settings
from voice_paste.shared.types import TranscriptionOutcome

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1
START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SESSION_LIMIT = timedelta(seconds=2)
"""API のセッションの上限時間。テストで待たずに済むよう、時計を進める量に合わせて短くする。"""

VOLUME_BEFORE = 0.8
"""録音前のシステム音量。"""

RETRY_BASE_SEC = 0.01
"""返送の再送の間隔の基数。テストで待てる短い値に差し替える。"""

WAIT_SEC = 5.0
"""ワーカースレッドの終わりなどを待つ上限。"""

START_TIMEOUT_SEC = 5.0
"""API の待ち受けの始まりを待つ上限。"""

REQUEST_TIMEOUT_SEC = 5.0
"""テストが API を叩くときのタイムアウト。"""

LOOPBACK = "127.0.0.1"


class Clock:
    """進められる今の時刻。"""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        """今の時刻を返す。"""
        return self.current


class FakeStream:
    """sounddevice.InputStream の偽物。止めて閉じたかを覚える。"""

    def __init__(self, on_frames: Callable[[np.ndarray], None]) -> None:
        self.on_frames = on_frames
        self.closed = False

    def stop(self) -> None:
        """入力を止める。"""

    def close(self) -> None:
        """入力を閉じたことを覚える。"""
        self.closed = True


class FakeMicrophone:
    """マイクの入力を開く関数の偽物。開いた回数を覚え、開けない状態にもできる。"""

    def __init__(self) -> None:
        self.streams: list[FakeStream] = []
        self.open_error: Exception | None = None

    def open_input(self, on_frames: Callable[[np.ndarray], None]) -> FakeStream:
        """入力を開く。open_error があれば例外にする。"""
        if self.open_error is not None:
            raise self.open_error
        stream = FakeStream(on_frames)
        self.streams.append(stream)
        return stream

    def feed(self, seconds: float) -> None:
        """今開いている入力へ、無音を seconds 秒分（0.1 秒ずつ）流す。閉じた入力には届かない。"""
        stream = self.streams[-1]
        if stream.closed:
            return
        chunk = np.zeros((int(SAMPLE_RATE * CHUNK_SEC), 1), dtype=np.int16)
        for _ in range(round(seconds / CHUNK_SEC)):
            stream.on_frames(chunk)


class FakeVolume:
    """システム音量の偽物。下げる・戻すを現在の音量に反映する。"""

    def __init__(self) -> None:
        self.level = VOLUME_BEFORE

    def lower_volume(self, ratio: float, fade_sec: float) -> float:
        """音量を ratio 倍に下げ、下げる前の音量を返す。"""
        before = self.level
        self.level = before * ratio
        return before

    def restore_volume(self, volume: float, fade_sec: float) -> None:
        """音量を volume へ戻す。"""
        self.level = volume


class FakeEngine:
    """文字起こしのエンジンの偽物。渡された録音のパスを覚え、決めた区間か例外を返す。"""

    def __init__(self) -> None:
        self.segments: list[str] = ["てすと"]
        self.error: Exception | None = None
        self.audio_paths: list[Path] = []

    def __call__(self, audio_path: Path, *, on_progress: object = None) -> list[str]:
        """録音のパスを覚え、error があれば送出し、無ければ区間を返す。"""
        self.audio_paths.append(audio_path)
        if self.error is not None:
            raise self.error
        return list(self.segments)


class CallbackReceiver:
    """返送先のテスト用の受け口。127.0.0.1 で待ち受け、届いた JSON を覚えて決めたステータスを返す。"""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.statuses: list[int] = []
        """先頭から順に返すステータス。尽きたら default_status を返す。"""
        self.default_status = 200
        self.delay_sec = 0.0
        """届いてからステータスを返すまで待つ秒数。"""
        self._lock = threading.Lock()
        receiver = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with receiver._lock:
                    receiver.received.append(body)
                    status = receiver.statuses.pop(0) if receiver.statuses else receiver.default_status
                time.sleep(receiver.delay_sec)
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                """アクセスログを出さない。"""

        self._server = ThreadingHTTPServer((LOOPBACK, 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """返送先として開始に渡す URL。"""
        return f"http://{LOOPBACK}:{self._server.server_address[1]}/result"

    def start(self) -> None:
        """待ち受けを始める。"""
        self._thread.start()

    def stop(self) -> None:
        """待ち受けを止める。"""
        self._server.shutdown()
        self._server.server_close()


@dataclass
class Stack:
    """立てた app と、差し替えた偽物。"""

    token: str
    port: int
    manager: SessionManager
    microphone: FakeMicrophone
    volume: FakeVolume
    engine: FakeEngine
    receiver: CallbackReceiver
    clock: Clock
    paths: AppPaths
    notify: MagicMock
    runner: ApiServerRunner
    http: httpx.Client

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """API へ POST する。authorized なら今回の起動のトークンを付ける。"""
        merged = {"Authorization": f"Bearer {self.token}"} if authorized else {}
        merged.update(headers or {})
        return self.http.post(path, json=json_body, headers=merged)

    def start_session(self) -> str:
        """返送先を受け口にして API の開始を呼び、202 を確かめてセッションの ID を返す。"""
        response = self.post("/sessions", json_body={"callback_url": self.receiver.url})
        assert response.status_code == 202
        return str(response.json()["session_id"])

    def session(self) -> Session | None:
        """今のセッションを返す。無ければ None。"""
        return self.manager._session

    def state(self) -> str | None:
        """今のセッションの状態を返す。セッションが無ければ None。"""
        session = self.manager._session
        return None if session is None else str(session.state)

    def recordings(self) -> list[Path]:
        """履歴に残った録音の WAV を返す。"""
        return sorted(self.paths.history_dir.rglob("*.wav"))

    def wait_for_idle(self) -> bool:
        """セッションが空（待機中）に戻るまで待ち、戻ったかを返す。"""
        return wait_until(lambda: self.manager._session is None)

    def wait_for_received(self, count: int) -> bool:
        """返送先に count 件届くまで待ち、届いたかを返す。"""
        return wait_until(lambda: len(self.receiver.received) >= count)


def wait_until(condition: Callable[[], bool], timeout_sec: float = WAIT_SEC) -> bool:
    """condition が True になるか timeout_sec が過ぎるまで待ち、True になったかを返す。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def _free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ返す。"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


def build_stack(tmp_path: Path) -> Stack:
    """偽物を差し込んだセッションを、本物の app と ApiServerRunner で立てる。"""
    paths = resolve_app_paths(tmp_path)
    settings = Settings()
    clock = Clock(START)
    microphone = FakeMicrophone()
    volume = FakeVolume()
    engine = FakeEngine()
    receiver = CallbackReceiver()
    receiver.start()
    notify = MagicMock()

    # 録音機には偽物の音量とマイクを渡す
    recorder = Recorder(
        lower_volume=volume.lower_volume,
        restore_volume=volume.restore_volume,
        open_input=microphone.open_input,
        get_settings=lambda: settings.recording,
    )

    # 呼び出し元へ返す出力先は、本物のタイムアウトと再送の回数で、再送の間隔だけ短くする
    callback_spec = next(spec for spec in OUTPUTS if spec.id == CALLBACK_OUTPUT_ID)
    callback_handler = partial(
        callback_spec.handler,
        post=partial(post_json, timeout_sec=CALLBACK_TIMEOUT_SEC),
        allowed_hosts=frozenset(),
        retry_count=CALLBACK_RETRY_COUNT,
        retry_base_sec=RETRY_BASE_SEC,
        sleep=time.sleep,
        jitter=lambda upper: upper,
    )
    outputs = (replace(callback_spec, handler=callback_handler),)

    def deliver_session(session: Session, outcome: TranscriptionOutcome) -> None:
        """Session を入口・出力先・返送先に分けて出力先の deliver へ渡す。"""
        deliver(
            session.entry,
            session.output_id,
            session.output_target,
            session.callback_url,
            outcome,
            enabled_ids=frozenset(),
            outputs=outputs,
        )

    deps = SessionDeps(
        start_recording=recorder.start,
        pause_recording=recorder.pause,
        resume_recording=recorder.resume,
        stop_recording=recorder.stop,
        discard_recording=recorder.discard,
        save_recording=partial(
            save_recording, history_enabled=True, paths=paths, now=clock
        ),
        transcribe=partial(transcribe, engine=engine),
        correct=lambda text: apply_glossary(text, []),
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=notify,
        now=clock,
        discard_temporary=partial(discard_temporary, paths=paths),
    )
    manager = SessionManager(deps, SESSION_LIMIT)

    # 本物の app を空きポートに立てる
    token = create_token()
    port = _free_port()
    session_api = SessionApiDeps(
        session_manager=manager,
        is_callback_allowed=partial(is_callback_allowed, allowed_hosts=frozenset()),
    )
    runner = ApiServerRunner(build_fastapi(session_api, token, port), port)
    assert runner.start(START_TIMEOUT_SEC)
    http = httpx.Client(base_url=f"http://{LOOPBACK}:{port}", timeout=REQUEST_TIMEOUT_SEC)
    return Stack(
        token=token.get_secret_value(),
        port=port,
        manager=manager,
        microphone=microphone,
        volume=volume,
        engine=engine,
        receiver=receiver,
        clock=clock,
        paths=paths,
        notify=notify,
        runner=runner,
        http=http,
    )


def stop_stack(stack: Stack) -> None:
    """立てた app・受け口・クライアントを止める。残ったセッションの録音は捨てる。"""
    stack.http.close()
    stack.runner.stop()
    stack.manager.close()
    stack.receiver.stop()


@dataclass
class OutputStack:
    """ホットキーのセッションを、配線した出力先へ届ける一式。キーボード・ブラウザのアダプタと間は偽物。"""

    manager: SessionManager
    adapters: MagicMock
    """呼ばれた順を 1 本の列で持つ親の Mock。`copy_to_clipboard`・`send_paste`・`send_enter`・`open_app_window`・`sleep` が偽物。"""
    notify: MagicMock
    engine: FakeEngine

    def confirm(self, output_id: str, output_target: str | None = None) -> None:
        """ホットキーのセッションを始め、output_id を選んで確定する。"""
        self.manager.start("hotkey")
        self.manager.complete(output_id=output_id, output_target=output_target)

    def wait_for_idle(self) -> bool:
        """セッションが空（待機中）に戻るまで待ち、戻ったかを返す。"""
        return wait_until(lambda: self.manager._session is None)

    def events(self) -> list[str]:
        """notify に渡された知らせの種類を、渡された順に返す。"""
        return [call.args[0] for call in self.notify.call_args_list]


def build_output_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings | None = None
) -> OutputStack:
    """ホットキーのセッションが、main.py の配線で作った出力先へ届く SessionManager を作る。"""
    settings = settings if settings is not None else Settings()
    paths = resolve_app_paths(tmp_path)
    clock = Clock(START)
    microphone = FakeMicrophone()
    volume = FakeVolume()
    engine = FakeEngine()
    notify = MagicMock()

    # キーボード・ブラウザのアダプタと間は、呼ばれた順を 1 本の列で見られる偽物に差し替える
    adapters = MagicMock()
    monkeypatch.setattr(main_module, "copy_to_clipboard", adapters.copy_to_clipboard)
    monkeypatch.setattr(main_module, "send_paste", adapters.send_paste)
    monkeypatch.setattr(main_module, "send_enter", adapters.send_enter)
    monkeypatch.setattr(main_module, "open_app_window", adapters.open_app_window)
    # main.py が出力先へ渡す time.sleep だけを差し替える（待つ側の time.sleep は本物のまま）
    monkeypatch.setattr(main_module, "time", SimpleNamespace(sleep=adapters.sleep))

    recorder = Recorder(
        lower_volume=volume.lower_volume,
        restore_volume=volume.restore_volume,
        open_input=microphone.open_input,
        get_settings=lambda: settings.recording,
    )
    enabled_ids = frozenset(output.id for output in settings.outputs if output.enabled)
    deliver_session = partial(
        _deliver_session, enabled_ids=enabled_ids, outputs=_wire_outputs(lambda: settings)
    )
    deps = SessionDeps(
        start_recording=recorder.start,
        pause_recording=recorder.pause,
        resume_recording=recorder.resume,
        stop_recording=recorder.stop,
        discard_recording=recorder.discard,
        save_recording=partial(save_recording, history_enabled=True, paths=paths, now=clock),
        transcribe=partial(transcribe, engine=engine),
        correct=lambda text: apply_glossary(text, []),
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=notify,
        now=clock,
        discard_temporary=partial(discard_temporary, paths=paths),
    )
    return OutputStack(
        manager=SessionManager(deps, SESSION_LIMIT), adapters=adapters, notify=notify, engine=engine
    )
