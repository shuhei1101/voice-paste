"""常駐アプリを pytest のプロセスの中で配線して動かす、E2E・非機能要件テストの補助。

`build_handlers` で配線し、録音の入力を WAV を流すものに差し替える（マイクもスピーカーも通らない）。
流す WAV は、Windows の音声合成（SAPI）で決めた文を書き出したものか、無音のもの。
システム音量・貼り付けのキーは差し替えて呼ばれた値を控え、通知も控える。
クリップボードと文字起こし（ローカルの Whisper・GPU）は実物を使う。常駐アプリの起動・トレイ・ホットキーの受付は通さず、
ホットキーの入口（`start_local_session`）から録音を始める。
"""

from __future__ import annotations

import math
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import resample_poly

import voice_paste.main as main_module
from tests.integration.helpers import wait_until
from tests.support.desktop import ProcessInfo, kill_tree, processes_with
from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.session import SessionManager
from voice_paste.integrations.whisper.client import WORKER_MODULE
from voice_paste.main import API_START_TIMEOUT_SEC, Handlers
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.settings import (
    LocalWhisperSettings,
    PasteAndSendSettings,
    Settings,
    TranscriptionSettings,
)
from voice_paste.shared.types import Entry, Recording

SPEECH_TEXT = "これはテストです"
"""録音として流す文（音声合成で WAV に書き出す）。"""

SPEECH_WORD = "テスト"
"""SPEECH_TEXT を起こした文字に含まれるはずの言葉。"""

CHUNK_FRAMES = 1024
"""録音の入力が 1 回に渡すフレーム数（sounddevice の既定の塊に近い値）。"""

SAPI_CREATE_FOR_WRITE = 3
"""音声合成の出力のファイルを書き込み用に作るモード（SSFMCreateForWrite）。"""

BROKEN_WAV_BYTES = b"voice-paste-e2e-broken-recording"
"""読めない録音の WAV の中身。"""

VOLUME_BEFORE = 0.8
"""録音前のシステム音量として控える値。"""

SILENCE_SEC = 2.0
"""何も話さない録音として流す無音の長さ。"""

PROCESSED_TIMEOUT_SEC = 120.0
"""確定した録音の処理（文字起こし・届ける）が終わるまで待つ上限（ワーカーの立て直しを含む）。"""

WORKER_CLIENT_LOGGER = "voice_paste.integrations.whisper.client"
"""文字起こしワーカーの窓口のロガーの名前。"""

WORKER_READY_LOG = "文字起こしワーカーが立ち上がった"
"""文字起こしワーカーが ready になったときのログの文の先頭。"""

WORKER_KILL_TIMEOUT_SEC = 90.0
"""文字起こしワーカーを 1 つ止めるまで待つ上限。"""

WORKER_READY_TIMEOUT_SEC = 60.0
"""やり直しのワーカーが ready になるまで待つ上限。"""

WORKER_KILL_INTERVAL_SEC = 0.2
"""文字起こしワーカーを止める試みの間隔。"""

REQUEST_TIMEOUT_SEC = 10.0
"""テストが API を叩くときのタイムアウト。"""

LOOPBACK = "127.0.0.1"


# === 流す WAV ===


def write_wav(wav_path: Path, samples: np.ndarray) -> Path:
    """16 kHz・モノラル・16 bit の WAV を書く。"""
    wavfile.write(wav_path, SAMPLE_RATE, samples)
    return wav_path


def write_silence(wav_path: Path, seconds: float) -> Path:
    """seconds 秒の無音の WAV を書く。"""
    return write_wav(wav_path, np.zeros(round(SAMPLE_RATE * seconds), dtype=np.int16))


def synthesize_speech(text: str, wav_path: Path) -> Path:
    """Windows の音声合成（SAPI）で text を読み上げた音を、16 kHz・モノラル・16 bit の WAV へ書き出す。"""
    import win32com.client

    # 1. 既定の声で、音声合成の出力をファイルへ向けて読み上げる（書き出す標本化周波数は声で決まる）
    raw_path = wav_path.with_suffix(".sapi.wav")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(raw_path), SAPI_CREATE_FOR_WRITE)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()

    # 2. 16 kHz に変えて書き直す
    rate, samples = wavfile.read(raw_path)
    assert samples.dtype == np.int16
    assert samples.ndim == 1
    divisor = math.gcd(SAMPLE_RATE, rate)
    resampled = resample_poly(samples, SAMPLE_RATE // divisor, rate // divisor)
    clipped = np.clip(np.rint(resampled), np.iinfo(np.int16).min, np.iinfo(np.int16).max)
    raw_path.unlink()
    return write_wav(wav_path, clipped.astype(np.int16))


def read_wav(wav_path: Path) -> np.ndarray:
    """16 kHz・モノラル・16 bit の WAV の音を返す。"""
    rate, samples = wavfile.read(wav_path)
    assert rate == SAMPLE_RATE
    assert samples.dtype == np.int16
    assert samples.ndim == 1
    return samples


def speech_input(tmp_path: Path, *, repeat: int = 1) -> WavInput:
    """SPEECH_TEXT を読み上げた WAV を repeat 回つなげて流す録音の入力を作る。"""
    samples = read_wav(synthesize_speech(SPEECH_TEXT, tmp_path / "speech.wav"))
    return WavInput(np.tile(samples, repeat))


def silence_input(
    tmp_path: Path, *, seconds: float = SILENCE_SEC, realtime: bool = False
) -> WavInput:
    """何も話さない無音の WAV（seconds 秒）を流す録音の入力を作る。"""
    samples = read_wav(write_silence(tmp_path / "silence.wav", seconds))
    return WavInput(samples, realtime=realtime)


# === 差し替えるもの ===


class _InputStream:
    """録音の入力のストリームの代わり。実時間で流しているスレッドがあれば、止めるときに終わらせる。"""

    def __init__(self) -> None:
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def feed_in_realtime(
        self, samples: np.ndarray, on_frames: Callable[[np.ndarray], None]
    ) -> None:
        """samples を、鳴る長さと同じ時間をかけて 1 塊ずつ渡すスレッドを始める。"""

        def _run() -> None:
            """止められるか音が尽きるまで、1 塊を渡しては 1 塊分の時間を待つ。"""
            for chunk in _chunks(samples):
                on_frames(chunk)
                if self._stopped.wait(CHUNK_FRAMES / SAMPLE_RATE):
                    return

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """流すスレッドを終わらせる。"""
        self._stopped.set()
        if self._thread is not None:
            self._thread.join()

    def close(self) -> None:
        """何もしない。"""


def _chunks(samples: np.ndarray) -> Iterator[np.ndarray]:
    """samples を CHUNK_FRAMES フレームずつの (n, 1) の塊にして順に返す。"""
    for start in range(0, len(samples), CHUNK_FRAMES):
        yield samples[start : start + CHUNK_FRAMES].reshape(-1, 1)


class WavInput:
    """録音の入力（マイクの入力を開く関数）の代わり。開かれると WAV の音を流し、開かれた回数を覚える。"""

    def __init__(self, samples: np.ndarray, *, realtime: bool = False) -> None:
        self.samples = samples
        self.realtime = realtime
        self.open_count = 0

    def __call__(self, on_frames: Callable[[np.ndarray], None]) -> _InputStream:
        """入力を開く。realtime ならスレッドで実時間で、そうでなければ開く中で全ての音を渡す。"""
        self.open_count += 1
        stream = _InputStream()
        if self.realtime:
            stream.feed_in_realtime(self.samples, on_frames)
        else:
            for chunk in _chunks(self.samples):
                on_frames(chunk)
        return stream


def ignore_lower_volume(_ratio: float, _fade_sec: float) -> float:
    """システム音量を何もせず、下げる前の音量として VOLUME_BEFORE を返す。"""
    return VOLUME_BEFORE


def ignore_restore_volume(_volume: float, _fade_sec: float) -> None:
    """システム音量を何もしない。"""


@dataclass
class VolumeLog:
    """システム音量の操作の代わり。下げた割合と、戻した音量を控える。"""

    lowered_ratios: list[float] = field(default_factory=list)
    restored: list[float] = field(default_factory=list)

    def lower(self, ratio: float, _fade_sec: float) -> float:
        """割合を控え、下げる前の音量として VOLUME_BEFORE を返す。"""
        self.lowered_ratios.append(ratio)
        return VOLUME_BEFORE

    def restore(self, volume: float, _fade_sec: float) -> None:
        """戻した音量を控える。"""
        self.restored.append(volume)


@dataclass
class KeyLog:
    """貼り付けのキーと Enter の送信の代わり。キーを送らずに、押された回数を控える。"""

    pasted: list[str] = field(default_factory=list)
    enters: int = 0

    def send_paste(self, paste_key: str) -> None:
        """貼り付けのキーが押されたことを控える。"""
        self.pasted.append(paste_key)

    def send_enter(self) -> None:
        """Enter が押されたことを控える。"""
        self.enters += 1


@dataclass
class Notifications:
    """ユーザーへの知らせ（画面・トレイへ渡すもの）の代わり。知らせの種類と理由を控える。"""

    events: list[tuple[str, str | None]] = field(default_factory=list)

    def __call__(self, event: str, detail: str | None) -> None:
        """知らせを控える。"""
        self.events.append((event, detail))

    def has(self, event: str) -> bool:
        """知らせの種類 event が控えにあるか。"""
        return any(kind == event for kind, _detail in self.events)


def break_saved_recordings(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存した録音の WAV の中身を、読めないものに書き換える（履歴にはファイルが残る）。"""
    original = main_module.save_recording

    def _save_broken(session_id: str, recording: Recording, **options: Any) -> Path:
        """本物で保存してから、書いたファイルの中身を読めないものにする。"""
        audio_path = original(session_id, recording, **options)
        audio_path.write_bytes(BROKEN_WAV_BYTES)
        return audio_path

    monkeypatch.setattr(main_module, "save_recording", _save_broken)


# === 配線した常駐アプリ ===


def make_settings(
    *, only_paste_and_send: bool = False, vad_threshold: float | None = None
) -> Settings:
    """既定の設定から、出力先を貼り付けて送信だけにするか、無音の区間を除く閾値を変えた設定を作る。"""
    outputs = [PasteAndSendSettings()] if only_paste_and_send else Settings().outputs
    local_whisper = (
        LocalWhisperSettings()
        if vad_threshold is None
        else LocalWhisperSettings(vad_threshold=vad_threshold)
    )
    return Settings(outputs=outputs, transcription=TranscriptionSettings(local_whisper=local_whisper))


def free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ返す。"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


@dataclass
class InProcessApi:
    """pytest のプロセスの中で待ち受けさせた API と、それを叩くクライアント。"""

    runner: ApiServerRunner
    http: httpx.Client
    token: str

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """API へ POST する。authorized なら今回のトークンを付ける。"""
        merged = {"Authorization": f"Bearer {self.token}"} if authorized else {}
        merged.update(headers or {})
        return self.http.post(path, json=json_body, headers=merged)

    def start_session(self, callback_url: str) -> tuple[httpx.Response, float]:
        """API の開始を呼び、応答と、応答までにかかったミリ秒を返す。"""
        started = time.perf_counter()
        response = self.post("/sessions", json_body={"callback_url": callback_url})
        return response, (time.perf_counter() - started) * 1000

    def close(self) -> None:
        """クライアントを閉じて待ち受けを止める。"""
        self.http.close()
        self.runner.stop()


@dataclass
class InProcessApp:
    """pytest のプロセスの中で配線した常駐アプリと、差し替えたものの控え。"""

    handlers: Handlers
    paths: AppPaths
    wav_input: WavInput
    volume: VolumeLog
    keys: KeyLog
    notifications: Notifications
    api: InProcessApi | None = None

    @property
    def manager(self) -> SessionManager:
        """セッション管理。"""
        return self.handlers.session_manager

    def start_hotkey(self) -> None:
        """ホットキーの入口から録音を始める（断られた理由は知らせに控える）。"""
        self.handlers.start_local_session(Entry.HOTKEY)

    def wait_idle(self, timeout_sec: float = PROCESSED_TIMEOUT_SEC) -> bool:
        """セッションが空（待機中）に戻るまで待ち、戻ったかを返す。"""
        return wait_until(lambda: self.manager.current() is None, timeout_sec)

    def history_files(self, suffix: str) -> list[Path]:
        """履歴に残ったファイルのうち、拡張子が suffix のものを返す。"""
        return sorted(self.paths.history_dir.rglob(f"*{suffix}"))

    def start_api(self) -> InProcessApi:
        """build_fastapi で組み立てた app を 127.0.0.1 の空きポートで待ち受けさせ、叩くクライアントを返す。"""
        token = create_token()
        port = free_port()
        runner = ApiServerRunner(build_fastapi(self.handlers.session_api, token, port), port)
        assert runner.start(API_START_TIMEOUT_SEC)
        http = httpx.Client(base_url=f"http://{LOOPBACK}:{port}", timeout=REQUEST_TIMEOUT_SEC)
        self.api = InProcessApi(runner=runner, http=http, token=token.get_secret_value())
        return self.api

    def close(self) -> None:
        """API を止め、残った録音を捨て、文字起こしのエンジンを止める。"""
        if self.api is not None:
            self.api.close()
        self.manager.close()
        self.handlers.stop_engine()


def start_inprocess_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings,
    wav_input: WavInput,
) -> InProcessApp:
    """録音の入力・システム音量・貼り付けのキー・通知を差し替えて build_handlers で配線し、モデルの読み込みを待つ。"""
    volume = VolumeLog()
    keys = KeyLog()
    notifications = Notifications()
    monkeypatch.setattr(main_module, "open_input", wav_input)
    monkeypatch.setattr(main_module, "lower_volume", volume.lower)
    monkeypatch.setattr(main_module, "restore_volume", volume.restore)
    monkeypatch.setattr(main_module, "send_paste", keys.send_paste)
    monkeypatch.setattr(main_module, "send_enter", keys.send_enter)
    paths = resolve_app_paths(tmp_path)
    handlers = main_module.build_handlers(
        settings, paths, notifications, lambda *_args, **_kwargs: None
    )
    return InProcessApp(
        handlers=handlers,
        paths=paths,
        wav_input=wav_input,
        volume=volume,
        keys=keys,
        notifications=notifications,
    )


# === 文字起こしワーカーの操作 ===


def worker_processes() -> list[ProcessInfo]:
    """この pytest のプロセスが起こした文字起こしワーカーのプロセス（ランチャーと本体）を返す。"""
    return processes_with(WORKER_MODULE, os.getpid())


def kill_workers() -> int:
    """文字起こしワーカーを止め、止めたワーカーの数（ランチャーの数）を返す。"""
    workers = worker_processes()
    worker_pids = {worker.pid for worker in workers}
    # ランチャー（親がワーカーでないもの）を子孫ごと止める
    roots = [worker for worker in workers if worker.parent_pid not in worker_pids]
    for root in roots:
        kill_tree(root.pid)
    return len(roots)


def worker_ready_count(caplog: pytest.LogCaptureFixture) -> int:
    """文字起こしワーカーが ready になった回数（立て直しを含む）を、控えたログから数える。

    テストは先に `caplog.set_level(logging.INFO, logger=WORKER_CLIENT_LOGGER)` を呼んでから配線する。
    """
    return sum(WORKER_READY_LOG in record.getMessage() for record in caplog.records)


def _kill_one_worker() -> bool:
    """文字起こしワーカーが現れるまで待って止め、止めたかを返す。"""
    deadline = time.monotonic() + WORKER_KILL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if kill_workers() > 0:
            return True
        time.sleep(WORKER_KILL_INTERVAL_SEC)
    return False


def kill_workers_twice(caplog: pytest.LogCaptureFixture) -> int:
    """文字起こしワーカーを止め、やり直しに立ったワーカーも ready になってから止める。止めた回数を返す。"""
    # 1. 立ち上がっているワーカーを止める（窓口が落ちたことに気づいて立て直す）
    ready_before = worker_ready_count(caplog)
    kills = int(_kill_one_worker())

    # 2. やり直しのワーカーが ready になるのを待って止める（読み込みの途中で止めると、やり直しの前に失敗する）
    assert wait_until(lambda: worker_ready_count(caplog) > ready_before, WORKER_READY_TIMEOUT_SEC)
    return kills + int(_kill_one_worker())
