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
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import resample_poly

import voice_paste.main as main_module
from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.processes import ProcessInfo, kill_tree, processes_with
from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.session import SessionApiDeps, SessionManager
from voice_paste.integrations.whisper.client import WORKER_MODULE
from voice_paste.main import API_START_TIMEOUT_SEC, SETTINGS_MODEL, Handlers
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
from voice_paste.runtime.timer import RepeatingTimer
from voice_paste.shared.errors import TranscriptionError
from voice_paste.shared.settings import (
    ApiSettings,
    ContinuousSettings,
    LocalWhisperSettings,
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

TRIM_AMPLITUDE = 200
"""読み上げた音の前後の無音を削るとき、これ以下の振れ幅を無音とみなす（int16）。"""

LONG_READING: tuple[tuple[str, str], ...] = (
    ("今日はいい天気です", "天気"),
    ("朝ごはんにパンを食べました", "パン"),
    ("来週の月曜日に会議があります", "会議"),
    ("犬が公園を走っています", "公園"),
    ("図書館で本を借りました", "図書館"),
    ("新しいパソコンを買いました", "パソコン"),
    ("電車が少し遅れています", "電車"),
    ("冷たいお茶を飲みました", "お茶"),
    ("電話番号を教えてください", "電話"),
    ("週末は家でゆっくり過ごします", "週末"),
    ("財布を机の上に置きました", "財布"),
    ("寒いので上着を着ます", "上着"),
    ("駅前の店でコーヒーを飲みます", "コーヒー"),
    ("写真を一枚撮ってください", "写真"),
    ("荷物を玄関に運びました", "荷物"),
    ("ありがとうございました", "ありがとう"),
)
"""話し続けて読み上げる文と、それぞれを起こした文字に含まれるはずの言葉。つなぐと話し声だけで約 28 秒になる。"""

READING_REPEAT_SENTENCES = len(LONG_READING) // 2
"""話し続ける読み上げを 45 秒以上にするために、LONG_READING の前半をもう 1 回つなぐときの文の数。"""

SEGMENT_CALLBACK_LATENCY_SEC = 4.0
"""区切ってから返送が届くまでの時間の決定値。"""

CONTINUOUS_END_TIMEOUT_SEC = 150.0
"""連続録音の終わりが返送先へ届くまで待つ上限（区間の文字起こしと上限での打ち切りを含む）。"""

CONTINUOUS_END_QUIET_SEC = 1.5
"""連続録音の終わりが届いた後、続きが届かないことを確かめるために待つ秒数。"""

PLAYED_OUT_TIMEOUT_SEC = 180.0
"""実時間で流す録音の入力が全ての音を渡し終えるまで待つ上限。"""

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


def _trim_silence(samples: np.ndarray) -> np.ndarray:
    """音の前後の無音（振れ幅が TRIM_AMPLITUDE 以下）を削る。"""
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) > TRIM_AMPLITUDE)
    assert loud.size > 0
    return samples[loud[0] : loud[-1] + 1]


def long_reading_texts() -> list[str]:
    """話し続けて読み上げる文を、文の間の無音を含めて 45 秒以上になるよう、LONG_READING の文と、その前半をもう 1 回つないで返す。"""
    texts = [sentence for sentence, _word in LONG_READING]
    return texts + texts[:READING_REPEAT_SENTENCES]


def speech_timeline_input(
    tmp_path: Path,
    items: Sequence[tuple[str, float]],
    *,
    lead_silence_sec: float = 0.0,
    tail_silence_sec: float = 0.0,
) -> WavInput:
    """(文, その文の前に挟む無音の秒数) の並びを 1 文ずつ読み上げ、前後の無音を削ってつないだ WAV を、実時間で流す録音の入力を作る。

    最初の文の前には、文ごとの無音ではなく lead_silence_sec 秒の無音を置く。最後の文の後に tail_silence_sec 秒の無音を足す（流し終えた後も無音を流し続けたいとき）。
    """
    # 1. 最初に無音を置き、1 文ずつ読み上げて前後の無音を削り、文の前に決めた長さの無音を挟んで並べる
    pieces: list[np.ndarray] = [np.zeros(round(SAMPLE_RATE * lead_silence_sec), dtype=np.int16)]
    for index, (text, gap_before_sec) in enumerate(items):
        spoken = _trim_silence(read_wav(synthesize_speech(text, tmp_path / f"sentence{index}.wav")))
        # 2 文目以降は、前の文との間に無音を挟む
        if index > 0:
            pieces.append(np.zeros(round(SAMPLE_RATE * gap_before_sec), dtype=np.int16))
        pieces.append(spoken)

    # 2. 最後の文の後に流し続ける無音を足して 1 本につなぐ
    pieces.append(np.zeros(round(SAMPLE_RATE * tail_silence_sec), dtype=np.int16))
    return WavInput(np.concatenate(pieces), realtime=True)


def speech_sequence_input(
    tmp_path: Path,
    texts: Sequence[str],
    *,
    gap_sec: float,
    lead_silence_sec: float = 0.0,
    tail_silence_sec: float = 0.0,
) -> WavInput:
    """texts を 1 文ずつ読み上げ、前後の無音を削って gap_sec の無音を挟んでつないだ WAV を、実時間で流す録音の入力を作る。"""
    return speech_timeline_input(
        tmp_path,
        [(text, gap_sec) for text in texts],
        lead_silence_sec=lead_silence_sec,
        tail_silence_sec=tail_silence_sec,
    )


# === 差し替えるもの ===


class _InputStream:
    """録音の入力のストリームの代わり。実時間で流しているスレッドがあれば、止めるときに終わらせる。"""

    def __init__(self) -> None:
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self.finished = threading.Event()
        """全ての音を渡し終えたか、止められて流すのをやめると立つ。"""

    def feed_in_realtime(
        self, samples: np.ndarray, on_frames: Callable[[np.ndarray], None]
    ) -> None:
        """samples を、鳴る長さと同じ時間をかけて 1 塊ずつ渡すスレッドを始める。"""

        def _run() -> None:
            """止められるか音が尽きるまで、1 塊を渡しては 1 塊分の時間を待つ。"""
            try:
                for chunk in _chunks(samples):
                    on_frames(chunk)
                    if self._stopped.wait(CHUNK_FRAMES / SAMPLE_RATE):
                        return
            finally:
                self.finished.set()

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
        self._last_stream: _InputStream | None = None

    def __call__(self, on_frames: Callable[[np.ndarray], None]) -> _InputStream:
        """入力を開く。realtime ならスレッドで実時間で、そうでなければ開く中で全ての音を渡す。"""
        self.open_count += 1
        stream = _InputStream()
        self._last_stream = stream
        if self.realtime:
            stream.feed_in_realtime(self.samples, on_frames)
        else:
            for chunk in _chunks(self.samples):
                on_frames(chunk)
            stream.finished.set()
        return stream

    def wait_played_out(self, timeout_sec: float = PLAYED_OUT_TIMEOUT_SEC) -> bool:
        """最後に開かれた入力が全ての音を渡し終えるまで待ち、渡し終えたかを返す（開かれていなければ False）。"""
        if self._last_stream is None:
            return False
        return self._last_stream.finished.wait(timeout_sec)

    @property
    def duration_sec(self) -> float:
        """流す音の長さ（秒）。"""
        return len(self.samples) / SAMPLE_RATE


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
        return self.count(event) > 0

    def count(self, event: str) -> int:
        """知らせの種類 event が控えに何回あるか。"""
        return sum(kind == event for kind, _detail in self.events)


def break_saved_recordings(monkeypatch: pytest.MonkeyPatch) -> None:
    """保存した録音の WAV の中身を、読めないものに書き換える（履歴にはファイルが残る）。"""
    original = main_module.save_recording

    def _save_broken(
        session_id: str, recording: Recording, segment_number: int | None = None, **options: Any
    ) -> Path:
        """本物で保存してから、書いたファイルの中身を読めないものにする。"""
        audio_path = original(session_id, recording, segment_number, **options)
        audio_path.write_bytes(BROKEN_WAV_BYTES)
        return audio_path

    monkeypatch.setattr(main_module, "save_recording", _save_broken)


def fail_transcription_of_segment(monkeypatch: pytest.MonkeyPatch, segment_number: int) -> None:
    """連続録音の通し番号 segment_number の区間だけ文字起こしに失敗させる（ほかの区間は本物で起こす）。"""
    original = main_module.transcribe

    def _transcribe(audio_path: Path, on_progress: Any = None, **options: Any) -> str:
        """区間の録音の名前の末尾が通し番号なので、対象の区間なら失敗させ、ほかは本物で起こす。"""
        if audio_path.stem.endswith(f"_{segment_number}"):
            raise TranscriptionError(f"区間 {segment_number} の文字起こしに失敗させた")
        return original(audio_path, on_progress, **options)

    monkeypatch.setattr(main_module, "transcribe", _transcribe)


# === 配線した常駐アプリ ===


def make_settings(
    *,
    only_paste_and_send: bool = False,
    vad_threshold: float | None = None,
    continuous_session_limit_sec: int | None = None,
) -> Settings:
    """既定の設定から、出力先を貼り付けて送信だけにするか、無音の区間を除く閾値・連続録音のセッションの上限時間を変えた設定を作る。

    連続録音のセッションの上限時間は、設定で許す下限（60 秒）より短い値も、テストで待てるよう検査を通さずに入れる。
    """
    outputs = [PasteAndSendSettings()] if only_paste_and_send else SETTINGS_MODEL().outputs
    local_whisper = (
        LocalWhisperSettings()
        if vad_threshold is None
        else LocalWhisperSettings(vad_threshold=vad_threshold)
    )
    api = ApiSettings()
    if continuous_session_limit_sec is not None:
        continuous = ContinuousSettings.model_construct(
            min_silence_sec=ContinuousSettings().min_silence_sec,
            session_limit_sec=continuous_session_limit_sec,
        )
        api = ApiSettings(continuous=continuous)
    return SETTINGS_MODEL(
        outputs=outputs,
        transcription=TranscriptionSettings(local_whisper=local_whisper),
        api=api,
    )


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
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """API へ POST する。authorized なら今回のトークンを付ける。"""
        merged = {"Authorization": f"Bearer {self.token}"} if authorized else {}
        merged.update(headers or {})
        return self.http.post(path, json=json_body, headers=merged)

    def start_session(
        self, callback_url: str, *, continuous: bool = False
    ) -> tuple[httpx.Response, float]:
        """API の開始（continuous なら連続録音）を呼び、応答と、応答までにかかったミリ秒を返す。"""
        started = time.perf_counter()
        body: dict[str, object] = {"callback_url": callback_url}
        # 連続録音のときだけ continuous を指定する（指定しない開始は 1 回の録音）
        if continuous:
            body["continuous"] = True
        response = self.post("/sessions", json_body=body)
        return response, (time.perf_counter() - started) * 1000

    def close(self) -> None:
        """クライアントを閉じて待ち受けを止める。"""
        self.http.close()
        self.runner.stop()


def serve_api(session_api: SessionApiDeps) -> InProcessApi:
    """build_fastapi で組み立てた app を 127.0.0.1 の空きポートで待ち受けさせ、叩くクライアントを返す。"""
    token = create_token()
    port = free_port()
    runner = ApiServerRunner(build_fastapi(session_api, token, port), port)
    assert runner.start(API_START_TIMEOUT_SEC)
    http = httpx.Client(base_url=f"http://{LOOPBACK}:{port}", timeout=REQUEST_TIMEOUT_SEC)
    return InProcessApi(runner=runner, http=http, token=token.get_secret_value())


def start_continuous(api: InProcessApi, receiver: CallbackReceiver) -> str:
    """連続録音を指定して API の開始を呼び、202 を確かめてセッションの ID を返す。"""
    response, _elapsed_ms = api.start_session(receiver.url, continuous=True)
    assert response.status_code == 202
    return str(response.json()["session_id"])


def complete_session(api: InProcessApi, session_id: str) -> None:
    """API の完了を呼び、202 を確かめる。"""
    assert api.post(f"/sessions/{session_id}/complete").status_code == 202


def wait_for_continuous_end(
    receiver: CallbackReceiver, *, offset: int = 0, timeout_sec: float = CONTINUOUS_END_TIMEOUT_SEC
) -> list[dict[str, Any]]:
    """連続録音の終わり（通し番号の無い返送）が届くのを待ち、続きが届かないことを確かめて、offset 件目以降に届いた返送を返す。"""
    assert wait_until(
        lambda: any(payload["segment_number"] is None for payload in receiver.received[offset:]),
        timeout_sec,
    )
    time.sleep(CONTINUOUS_END_QUIET_SEC)
    return list(receiver.received[offset:])


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
    limit_timer: RepeatingTimer | None = None

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
        self.api = serve_api(self.handlers.session_api)
        return self.api

    def start_limit_timer(self) -> None:
        """常駐中と同じ間隔で、上限時間を過ぎた API のセッションを打ち切るタイマーを回す。"""
        self.limit_timer = RepeatingTimer(
            self.manager.truncate_if_expired, main_module.SESSION_LIMIT_CHECK_INTERVAL_SEC
        )
        self.limit_timer.start()

    def close(self) -> None:
        """上限のタイマーと API を止め、残った録音を捨て、文字起こしのエンジンを止める。"""
        if self.limit_timer is not None:
            self.limit_timer.stop()
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
