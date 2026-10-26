"""結合テスト（常駐アプリの API とセッション）の偽物と組み立て。

本物の app（build_fastapi）を ApiServerRunner で 127.0.0.1 の空きポートに立て、httpx で叩く。
マイク・システム音量・文字起こしのエンジンは偽物にし、履歴は一時フォルダに書く。
返送先は、テストが 127.0.0.1 に立てる受信先にする。

外の端末のブラウザ向けの API（/web/）は、同じ app の ブラウザの音声のキュー（WebJobQueue）を本物のまま立て、
文字起こしのエンジンだけを同じ偽物（FakeEngine）に差し替える。履歴は一時フォルダに書く。

ホットキー・トレイのセッションが確定で選んだ出力先へ届く結合テストは、API を立てず、
main.py の配線（_wire_outputs）で作った出力先を使い、キーボード・ブラウザのアダプタと間だけを偽物にする（build_output_stack）。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
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

from tests.unit.voice_paste.features.recording.helpers import ScriptedDetector, windows
from voice_paste.features.correction import (
    apply_glossary,
    pick_glossary_preset,
    resolve_glossary_presets,
)
from voice_paste.features.history import (
    append_text,
    discard_temporary,
    save_recording,
    store_web_audio,
)
from voice_paste.features.outputs import OUTPUTS, deliver, is_callback_allowed
from voice_paste.features.outputs.registry import CALLBACK_OUTPUT_ID
from voice_paste.features.recording import Recorder
from voice_paste.features.session import (
    Session,
    SessionApiDeps,
    SessionDeps,
    SessionManager,
)
from voice_paste.features.transcription.service import transcribe
from voice_paste.features.web_transcription import (
    GlossaryPresetChoices,
    WebApiDeps,
    WebJobQueue,
    WebTranscriptionDeps,
)
from voice_paste.features.web_transcription.service import (
    WEB_FINISHED_JOBS_KEPT,
    WEB_QUEUE_LIMIT,
)
from voice_paste.integrations.audio.probe import probe_audio
from voice_paste.integrations.http.client import post_json
import voice_paste.main as main_module
from voice_paste.features.outputs.callback.service import (
    CALLBACK_RETRY_COUNT,
    CALLBACK_TIMEOUT_SEC,
)
from voice_paste.features.outputs.types import OutputDeps
from voice_paste.main import (
    SETTINGS_MODEL,
    _deliver_session,
    _make_paste,
    _wire_outputs,
    _wire_preset_kinds,
)
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import Preset, Settings
from voice_paste.shared.types import GlossaryEntry, TranscriptionOutcome

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1
START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SESSION_LIMIT = timedelta(seconds=2)
"""API のセッションの上限時間。テストで待たずに済むよう、時計を進める量に合わせて短くする。"""

CONTINUOUS_SESSION_LIMIT = timedelta(seconds=5)
"""連続録音のセッションの上限時間。1 回の録音の上限時間より長くし、時計を進める量で打ち切りを分ける。"""

SPEECH_SEC = 1.0
"""連続録音の区間の話し声の長さ（話し声の判定の偽物が返す）。"""

CUT_SILENCE_SEC = 2.5
"""区間を区切る無音の長さ。設定の区切る無音の長さ（既定 2 秒）を超える。"""

CUT_CYCLE_SEC = SPEECH_SEC + CUT_SILENCE_SEC
"""話し声から区切りまでの音の長さ。これだけ流すと区間が 1 つ区切れる。"""

SEGMENT_PHASES = ((0.9, windows(SPEECH_SEC)), (0.0, windows(CUT_SILENCE_SEC)))
"""区間が 1 つ区切れる話し声の確率の並び（話し声の後に区切りの無音）。"""

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

WEB_ORIGIN = "https://voice.example.com"
"""設定の許す Origin（api.allowed_web_origins）に入れる、ゲートウェイの公開のオリジン。"""


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
        self.error_on_calls: set[int] = set()
        """例外にする呼び出しの番号（1 始まり）。連続録音の区間のうち特定の区間だけを失敗させる。"""
        self.audio_paths: list[Path] = []
        self.hook: Callable[[Path, Callable[[float, float], None]], None] | None = None
        """呼び出しの最初に呼ぶ関数（録音のパスと進みを知らせる関数を受ける）。進みを返す・テストが放すまで待つ、に使う。"""
        self.release = threading.Event()
        """hook が待つ合図。テストが放す。後片付けでも放す。"""

    def __call__(
        self, audio_path: Path, *, on_progress: object = None, hint: str | None = None
    ) -> list[str]:
        """録音のパスを覚え、hook があれば呼び、error があれば（error_on_calls の番号の呼び出しなら）送出し、無ければ区間を返す。"""
        self.audio_paths.append(audio_path)
        if self.hook is not None:
            self.hook(audio_path, on_progress)  # type: ignore[arg-type] 文字起こしが渡す進みを知らせる関数
        if self.error is not None:
            raise self.error
        if len(self.audio_paths) in self.error_on_calls:
            raise EngineError("この区間の文字起こしに失敗した")
        return list(self.segments)


@dataclass
class VadScript:
    """連続録音を開始たびに作る話し声の判定の偽物の、確率の並びと失敗の指定。"""

    phases: tuple[tuple[float, int], ...] = ()
    """(話し声の確率, 窓の数) の並び。"""
    tail: float = 0.0
    """並びを使い切った後の確率。"""
    fail_on_call: int | None = None
    """この番号（1 始まり）の窓の判定で error を送出する。"""
    error: Exception | None = None

    def create(self) -> ScriptedDetector:
        """今の並びで、状態を持たない新しい話し声の判定を作る。"""
        return ScriptedDetector(
            self.phases, tail=self.tail, fail_on_call=self.fail_on_call, error=self.error
        )


class CallbackReceiver:
    """返送先のテスト用の受信先。127.0.0.1 で待ち受け、届いた JSON を覚えて決めたステータスを返す。"""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        """届いた要求のヘッダー（小文字の名前）。received と同じ順。"""
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
                    receiver.headers.append({key.lower(): value for key, value in self.headers.items()})
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
class WebSettings:
    """ブラウザの音声のジョブが、起こすたびに引く設定（テストが途中で変えられる）。"""

    history_enabled: bool = True
    """履歴を残す設定か。"""
    glossary: list[GlossaryEntry] = field(default_factory=list)
    """補正に使う用語集の行（プリセットごとの行 `preset_glossaries` に無いプリセットで使う）。"""
    preset_glossaries: dict[str, list[GlossaryEntry]] = field(default_factory=dict)
    """用語集のプリセットの名前ごとの、補正に使う用語集の行。"""
    settings: Settings = field(default_factory=SETTINGS_MODEL)
    """今の設定（用語集のプリセットの一覧と、設定で選んでいるプリセットを引く）。"""


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
    vad: VadScript
    web_queue: WebJobQueue
    web_tmp_dir: Path
    web: WebSettings
    settings: Settings
    """立てたときの設定（用語集のプリセットの一覧の確かめと、設定で選んでいるプリセットの確認に使う）。"""

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """API へ POST する。authorized なら今回の起動のトークンを付ける。"""
        merged = {"Authorization": f"Bearer {self.token}"} if authorized else {}
        merged.update(headers or {})
        return self.http.post(path, json=json_body, headers=merged)

    def post_audio(
        self,
        data: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
        headers: dict[str, str] | None = None,
        field_name: str = "audio",
        origin: str | None = WEB_ORIGIN,
        glossary_preset: str | None = None,
    ) -> httpx.Response:
        """ゲートウェイを通した形（Host は localhost:{ポート}、許す Origin つき、トークン無し）で、音声を multipart で POST /web/transcriptions へ送る。origin が None なら Origin を付けず、glossary_preset が None なら glossary_preset の項目を付けない。"""
        merged = {"Host": f"localhost:{self.port}"}
        if origin is not None:
            merged["Origin"] = origin
        merged.update(headers or {})
        form = None if glossary_preset is None else {"glossary_preset": glossary_preset}
        return self.http.post(
            "/web/transcriptions",
            files={field_name: (filename, data, content_type)},
            data=form,
            headers=merged,
        )

    def get_glossary_presets(self, *, origin: str | None = None) -> httpx.Response:
        """ゲートウェイを通した形（Host は localhost:{ポート}、トークン無し）で、GET /web/glossary-presets を呼ぶ。origin が None なら Origin を付けない。"""
        merged = {"Host": f"localhost:{self.port}"}
        if origin is not None:
            merged["Origin"] = origin
        return self.http.get("/web/glossary-presets", headers=merged)

    def post_audio_chunked(self, data: bytes, *, filename: str = "recording.webm") -> httpx.Response:
        """Content-Length を付けず chunked で、音声を multipart で POST /web/transcriptions へ送る（許す Origin つき）。"""
        boundary = "----chunked-boundary"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
            "Content-Type: audio/webm\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        chunk = 4096

        def body() -> Any:  # noqa: ANN401 httpx に渡すバイト列の生成器
            yield head
            for start in range(0, len(data), chunk):
                yield data[start : start + chunk]
            yield tail

        return self.http.post(
            "/web/transcriptions",
            content=body(),
            headers={
                "Host": f"localhost:{self.port}",
                "Origin": WEB_ORIGIN,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

    def get_job(self, job_id: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        """ゲートウェイを通した形（Host は localhost:{ポート}、Origin 無し、トークン無し）で、GET /web/transcriptions/{job_id} を呼ぶ。"""
        merged = {"Host": f"localhost:{self.port}"}
        merged.update(headers or {})
        return self.http.get(f"/web/transcriptions/{job_id}", headers=merged)

    def wait_for_job(self, job_id: str, state: str) -> bool:
        """そのジョブの state が state になるまで待ち、なったかを返す。"""
        return wait_until(lambda: self.get_job(job_id).json().get("state") == state)

    def submit_audio(
        self, data: bytes, *, filename: str = "recording.webm", glossary_preset: str | None = None
    ) -> str:
        """音声を（glossary_preset があればその指定で）受け付けさせ、202 を確かめてジョブの ID を返す。"""
        response = self.post_audio(data, filename=filename, glossary_preset=glossary_preset)
        assert response.status_code == 202
        return str(response.json()["job_id"])

    def start_session(self, *, continuous: bool = False) -> str:
        """返送先を受信先にして API の開始（continuous なら連続録音）を呼び、202 を確かめてセッションの ID を返す。"""
        body: dict[str, object] = {"callback_url": self.receiver.url}
        if continuous:
            body["continuous"] = True
        response = self.post("/sessions", json_body=body)
        assert response.status_code == 202
        return str(response.json()["session_id"])

    def set_segments(self, count: int, *, tail: float = 0.0) -> None:
        """話し声の判定の偽物を、区間が count 個区切れる並び（話し声の後に区切りの無音）にする。tail は並びの後の確率。連続録音を開始前に呼ぶ（判定は始めるたびに今の並びで作る）。"""
        self.vad.phases = SEGMENT_PHASES * count
        self.vad.tail = tail

    def feed_segments(self, count: int) -> None:
        """区間が count 個区切れるだけの音を、今開いている入力へ流す。"""
        self.microphone.feed(CUT_CYCLE_SEC * count)

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


def make_audio(kind: str, tmp_path: Path) -> bytes:
    """kind（webm・mp4・video_only_mp4）の短い音声のバイト列を、PyAV で書き出して返す。"""
    import av

    path = tmp_path / f"audio_{kind}"
    if kind == "video_only_mp4":
        # 音声のストリームを持たない、映像だけの mp4
        with av.open(str(path), "w", format="mp4") as out:
            stream = out.add_stream("mpeg4", rate=10)
            stream.width = 64
            stream.height = 64
            stream.pix_fmt = "yuv420p"
            for _ in range(10):
                frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24")
                out.mux(stream.encode(frame))
            out.mux(stream.encode(None))
        return path.read_bytes()

    container, codec, rate, options = {
        "webm": ("webm", "libopus", 48000, {}),
        "mp4": ("mp4", "aac", 44100, {"movflags": "frag_keyframe+empty_moov+default_base_moof"}),
    }[kind]
    wav = tmp_path / "source.wav"
    from scipy.io import wavfile

    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    wavfile.write(wav, SAMPLE_RATE, (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16))
    with av.open(str(wav)) as src, av.open(str(path), "w", format=container, options=options) as dst:
        stream = dst.add_stream(codec, rate=rate)
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=stream.rate)
        for frame in src.decode(audio=0):
            for resampled in resampler.resample(frame):
                dst.mux(stream.encode(resampled))
        for resampled in resampler.resample(None):
            dst.mux(stream.encode(resampled))
        dst.mux(stream.encode(None))
    return path.read_bytes()


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


def build_stack(
    tmp_path: Path,
    *,
    web_worker: bool = True,
    web_max_pending: int = WEB_QUEUE_LIMIT,
    web_max_finished: int = WEB_FINISHED_JOBS_KEPT,
    settings: Settings | None = None,
) -> Stack:
    """偽物を差し込んだセッションを、本物の app と ApiServerRunner で立てる。

    ブラウザの音声のキューは本物で、web_worker が偽ならワーカースレッドを立てない（積んだジョブは取り出されない）。
    """
    paths = resolve_app_paths(tmp_path)
    settings = settings if settings is not None else SETTINGS_MODEL()
    clock = Clock(START)
    microphone = FakeMicrophone()
    volume = FakeVolume()
    engine = FakeEngine()
    receiver = CallbackReceiver()
    receiver.start()
    notify = MagicMock()
    vad = VadScript()

    # 録音機には偽物の音量とマイクと、話し声の判定を作る関数を渡す
    recorder = Recorder(
        lower_volume=volume.lower_volume,
        restore_volume=volume.restore_volume,
        open_input=microphone.open_input,
        get_settings=lambda: settings.recording,
        create_speech_detector=vad.create,
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
            session.output_preset,
            session.callback_url,
            outcome,
            enabled_ids=frozenset(),
            outputs=outputs,
            preset_kinds=(),
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
        transcribe=partial(transcribe, engine=engine, get_hint=lambda: None),
        correct=lambda text, glossary_preset: apply_glossary(text, []),
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=notify,
        now=clock,
        discard_temporary=partial(discard_temporary, paths=paths),
        report_progress=lambda position_sec, duration_sec: None,
        start_continuous_recording=partial(
            recorder.start_continuous, min_silence_sec=settings.api.continuous.min_silence_sec
        ),
        stop_continuous_recording=recorder.stop_continuous,
    )
    manager = SessionManager(deps, SESSION_LIMIT, CONTINUOUS_SESSION_LIMIT)

    # 本物の app を空きポートに立てる
    token = create_token()
    port = _free_port()
    session_api = SessionApiDeps(
        session_manager=manager,
        is_callback_allowed=partial(is_callback_allowed, allowed_hosts=frozenset()),
        glossary_preset_exists=lambda name: any(
            preset.name == name
            for preset in resolve_glossary_presets(settings, paths.settings_file.parent)
        ),
    )
    web = WebSettings(settings=settings)
    settings_dir = paths.settings_file.parent

    def web_correct(text: str, glossary_preset: str | None) -> str:
        """ジョブのプリセット（None は設定で選んでいるプリセット）の用語集の行で補正する。"""
        name = pick_glossary_preset(web.settings, settings_dir, requested=glossary_preset).name
        return apply_glossary(text, web.preset_glossaries.get(name, web.glossary))

    def web_glossary_preset_exists(name: str) -> bool:
        """今の設定の用語集のプリセットの一覧に、その名前があるか。"""
        return any(
            preset.name == name for preset in resolve_glossary_presets(web.settings, settings_dir)
        )

    def web_list_glossary_presets() -> GlossaryPresetChoices:
        """今の設定の用語集のプリセットの名前の一覧と、設定で選んでいるプリセットの名前を返す。"""
        presets = resolve_glossary_presets(web.settings, settings_dir)
        active = pick_glossary_preset(web.settings, settings_dir)
        return GlossaryPresetChoices(presets=[preset.name for preset in presets], active=active.name)

    web_queue = WebJobQueue(
        WebTranscriptionDeps(
            store_audio=lambda job_id, source: store_web_audio(
                job_id, source, history_enabled=web.history_enabled, paths=paths, now=clock
            ),
            transcribe=partial(transcribe, engine=engine, get_hint=lambda: None),
            correct=web_correct,
            append_text=partial(append_text, paths=paths),
            discard_temporary=partial(discard_temporary, paths=paths),
        ),
        max_pending=web_max_pending,
        max_finished=web_max_finished,
    )
    web_tmp_dir = paths.tmp_dir / "web"
    if web_worker:
        web_queue.start(web_tmp_dir)
    else:
        web_tmp_dir.mkdir(parents=True, exist_ok=True)
    web_api = WebApiDeps(
        queue=web_queue,
        probe_audio=probe_audio,
        tmp_dir=web_tmp_dir,
        glossary_preset_exists=web_glossary_preset_exists,
        list_glossary_presets=web_list_glossary_presets,
    )
    app = build_fastapi(
        session_api, token, port, web_api=web_api, allowed_web_origins=[WEB_ORIGIN]
    )
    runner = ApiServerRunner(app, port)
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
        vad=vad,
        web_queue=web_queue,
        web_tmp_dir=web_tmp_dir,
        web=web,
        settings=settings,
    )


def stop_stack(stack: Stack) -> None:
    """立てた app・受信先・クライアントを止める。残ったセッションの録音は捨てる。"""
    stack.engine.release.set()
    stack.http.close()
    stack.runner.stop()
    stack.manager.close()
    stack.web_queue.close()
    stack.receiver.stop()


@dataclass
class OutputStack:
    """ホットキーのセッションを、配線した出力先へ届ける一式。キーボード・ブラウザのアダプタと間は偽物。"""

    manager: SessionManager
    adapters: MagicMock
    """呼ばれた順を 1 本の列で持つ親の Mock。`copy_to_clipboard`・`send_paste`・`send_enter`・`open_app_window`・`sleep` が偽物。"""
    notify: MagicMock
    engine: FakeEngine

    def confirm(self, output_id: str | None = None, preset: Preset | None = None) -> None:
        """ホットキーのセッションを始め、固定の出力先かカスタムプリセットを選んで確定する。"""
        self.manager.start("hotkey")
        self.manager.complete(output_id=output_id, preset=preset)

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
    settings = settings if settings is not None else SETTINGS_MODEL()
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
        create_speech_detector=VadScript().create,
    )
    enabled_ids = frozenset(output.id for output in settings.outputs if output.enabled)
    # main.py の build_handlers と同じ束を、偽物にした外部連携で組む
    output_deps = OutputDeps(
        copy=adapters.copy_to_clipboard,
        paste=_make_paste(lambda: settings),
        send_enter=adapters.send_enter,
        sleep=adapters.sleep,
        jitter=lambda upper: upper,
        post=post_json,
        get_settings=lambda: settings,
        notify_copied=lambda text: None,
    )
    deliver_session = partial(
        _deliver_session,
        enabled_ids=enabled_ids,
        outputs=_wire_outputs(output_deps, OUTPUTS),
        preset_kinds=_wire_preset_kinds(lambda: settings),
    )
    deps = SessionDeps(
        start_recording=recorder.start,
        pause_recording=recorder.pause,
        resume_recording=recorder.resume,
        stop_recording=recorder.stop,
        discard_recording=recorder.discard,
        save_recording=partial(save_recording, history_enabled=True, paths=paths, now=clock),
        transcribe=partial(transcribe, engine=engine, get_hint=lambda: None),
        correct=lambda text, glossary_preset: apply_glossary(text, []),
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=notify,
        now=clock,
        discard_temporary=partial(discard_temporary, paths=paths),
        report_progress=lambda position_sec, duration_sec: None,
        start_continuous_recording=partial(
            recorder.start_continuous, min_silence_sec=settings.api.continuous.min_silence_sec
        ),
        stop_continuous_recording=recorder.stop_continuous,
    )
    return OutputStack(
        manager=SessionManager(deps, SESSION_LIMIT, CONTINUOUS_SESSION_LIMIT),
        adapters=adapters,
        notify=notify,
        engine=engine,
    )
