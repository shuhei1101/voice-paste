"""常駐アプリを pytest のプロセスの中で配線して動かす、E2E・非機能要件テストの補助。

`build_handlers` で配線し、録音の入力を WAV を流すものに差し替える（マイクもスピーカーも通らない）。
流す WAV は、音声合成（Windows は SAPI、Linux は Open JTalk）で決めた文を書き出したものか、無音のもの。
システム音量・貼り付けのキーは差し替えて呼ばれた値を控え、通知も控える。
クリップボードと文字起こし（ローカルの Whisper・GPU）は実物を使う。常駐アプリの起動・トレイ・ホットキーの受付は通さず、
ホットキーの入口（`start_local_session`）から録音を始める。
"""

from __future__ import annotations

import ctypes
import math
import os
import re
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from ctypes import wintypes
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from scipy.io import wavfile
from scipy.signal import resample_poly

import voice_paste.main as main_module
from tests.integration.helpers import CallbackReceiver, wait_until
from tests.support.processes import ProcessInfo, descendants, processes_with
from tests.support.settings import default_output, load_test_default_settings, make_test_settings
from tests.support.web_body import CONTENT_TYPE, chunks_of
from voice_paste.features.recording.client import SAMPLE_RATE
from voice_paste.features.session import SessionApiDeps, SessionManager
from voice_paste.features.web_transcription import WebApiDeps
from voice_paste.integrations.whisper.client import WORKER_MODULE
from voice_paste.main import API_START_TIMEOUT_SEC, Handlers
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.runtime.timer import RepeatingTimer
from voice_paste.shared.errors import TranscriptionError
from voice_paste.shared.os_kind import (
    CURRENT_OS,
    Feature,
    OsKind,
    detect_display_session,
    unavailable_features,
)
from voice_paste.shared.settings import (
    GlossaryPresetSettings,
    GlossarySettings,
    Settings,
)
from voice_paste.shared.types import EnterModifier, Entry, Recording

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

LOWERS_VOLUME = Feature.LOWER_VOLUME not in unavailable_features(CURRENT_OS)
"""動いている OS で、常駐アプリが録音中にシステム音量を下げて終わったら戻すか（Linux は下げない）。"""

HAS_WEB_TRANSCRIPTION = Feature.WEB_TRANSCRIPTION not in unavailable_features(CURRENT_OS)
"""動いている OS で、常駐アプリが外の端末のブラウザの文字起こし（`/web/`）を持つか（Linux は持たない）。"""

requires_web_transcription = pytest.mark.skipif(
    not HAS_WEB_TRANSCRIPTION,
    reason="常駐アプリはこの OS で外の端末のブラウザの文字起こしを持たない",
)
"""外の端末の画面のケースを、ブラウザの文字起こしを持たない OS（Linux）では skip するマーカー。"""

OPEN_JTALK_HOME_ENV = "VOICE_PASTE_OPEN_JTALK_HOME"
"""Linux で Open JTalk を展開した置き場所を替える環境変数。"""

OPEN_JTALK_DEFAULT_HOME = Path.home() / ".local/opt/open-jtalk"
"""Linux で Open JTalk を sudo を使わずに展開した既定の置き場所（開発コマンド『環境構築（クローン直後）』の手順 3）。"""

OPEN_JTALK_LIBRARY_DIR = "usr/lib/x86_64-linux-gnu"
OPEN_JTALK_COMMAND = "usr/bin/open_jtalk"
OPEN_JTALK_DICTIONARY_DIR = "var/lib/mecab/dic/open-jtalk/naist-jdic"
OPEN_JTALK_VOICE_FILE = "usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice"
"""Open JTalk の置き場所からの、読み込むライブラリ・コマンド・辞書・声の相対パス。"""

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
    ("明日は晴れるでしょう", "晴れ"),
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

HOLD_TIMEOUT_SEC = 30.0
"""差し替えた文字起こしを、放すまで待たせる上限（テストの途中で失敗しても、後始末がこれより長く止まらない）。"""

WORKER_CLIENT_LOGGER = "voice_paste.integrations.whisper.client"
"""文字起こしワーカーの窓口のロガーの名前。"""

WORKER_READY_LOG = "文字起こしワーカーが立ち上がった"
"""文字起こしワーカーが ready になったときのログの文の先頭。"""

WORKER_READY_TIMEOUT_SEC = 60.0
"""やり直しのワーカーが ready になるまで待つ上限。"""

READY_PID_PATTERN = re.compile(r"pid (\d+)")
"""文字起こしワーカーが ready になったときのログの文から、ランチャーの番号を取る正規表現。"""

TOOLHELP_SNAPSHOT_PROCESS = 0x2
"""Toolhelp のスナップショットに、プロセスを入れる指定（TH32CS_SNAPPROCESS）。"""

TOOLHELP_EXE_FILE_CHARS = 260
"""Toolhelp のプロセスの 1 行が持つ、実行ファイル名の最大の文字数（MAX_PATH）。"""

WORKER_READY_POLL_SEC = 0.05
"""やり直しのワーカーが ready になったかを確かめる間隔（ready の直後に止めるため短くする）。"""

REQUEST_TIMEOUT_SEC = 10.0
"""テストが API を叩くときのタイムアウト。"""

LARGE_BODY_TIMEOUT_SEC = 120.0
"""本文の上限に近い大きさの音声を送信するときのタイムアウト。"""

LOOPBACK = "127.0.0.1"


# === 流す WAV ===


def write_wav(wav_path: Path, samples: np.ndarray) -> Path:
    """16 kHz・モノラル・16 bit の WAV を書く。"""
    wavfile.write(wav_path, SAMPLE_RATE, samples)
    return wav_path


def write_silence(wav_path: Path, seconds: float) -> Path:
    """seconds 秒の無音の WAV を書く。"""
    return write_wav(wav_path, np.zeros(round(SAMPLE_RATE * seconds), dtype=np.int16))


def expected_lowered_ratios(ratio: float) -> list[float]:
    """録音を 1 回始めたときに、システム音量を下げた割合の控えの期待値（下げない OS では空）。"""
    return [ratio] if LOWERS_VOLUME else []


def expected_restored_volumes() -> list[float]:
    """録音を 1 回終えたときに、システム音量を戻した値の控えの期待値（下げない OS では空）。"""
    return [VOLUME_BEFORE] if LOWERS_VOLUME else []


def synthesize_speech(text: str, wav_path: Path) -> Path:
    """音声合成（Windows は SAPI、Linux は Open JTalk）で text を読み上げた音を、16 kHz・モノラル・16 bit の WAV へ書き出す。"""
    # 1. OS の音声合成で、読み上げた音を一時の WAV へ書き出す（書き出す標本化周波数は声で決まる）
    # Windows か
    if CURRENT_OS == OsKind.WINDOWS:
        # そう: SAPI の既定の声で書き出す
        raw_path = wav_path.with_suffix(".sapi.wav")
        _synthesize_sapi(text, raw_path)
    else:
        # 違う: ユーザーの配下に展開した Open JTalk で書き出す
        raw_path = wav_path.with_suffix(".jtalk.wav")
        _synthesize_open_jtalk(text, raw_path)

    # 2. 16 kHz に変えて書き直す
    rate, samples = wavfile.read(raw_path)
    assert samples.dtype == np.int16
    assert samples.ndim == 1
    divisor = math.gcd(SAMPLE_RATE, rate)
    resampled = resample_poly(samples, SAMPLE_RATE // divisor, rate // divisor)
    clipped = np.clip(np.rint(resampled), np.iinfo(np.int16).min, np.iinfo(np.int16).max)
    raw_path.unlink()
    return write_wav(wav_path, clipped.astype(np.int16))


def _synthesize_sapi(text: str, raw_path: Path) -> None:
    """Windows の音声合成（SAPI）の既定の声で、text を読み上げた音を raw_path の WAV へ書き出す。"""
    import win32com.client

    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(raw_path), SAPI_CREATE_FOR_WRITE)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()


def _synthesize_open_jtalk(text: str, raw_path: Path) -> None:
    """Open JTalk で、text を読み上げた音を raw_path の WAV（48 kHz）へ書き出す。

    パッケージを入れずに展開しているため、open_jtalk が読む libHTSEngine の場所を LD_LIBRARY_PATH で渡す。
    """
    home = Path(os.environ.get(OPEN_JTALK_HOME_ENV, OPEN_JTALK_DEFAULT_HOME))
    subprocess.run(  # noqa: S603 置き場所の下の固定の open_jtalk
        [
            str(home / OPEN_JTALK_COMMAND),
            "-x",
            str(home / OPEN_JTALK_DICTIONARY_DIR),
            "-m",
            str(home / OPEN_JTALK_VOICE_FILE),
            "-ow",
            str(raw_path),
        ],
        input=text.encode("utf-8"),
        env={**os.environ, "LD_LIBRARY_PATH": str(home / OPEN_JTALK_LIBRARY_DIR)},
        capture_output=True,
        check=True,
    )


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

    最初の文の前には、文ごとの無音ではなく lead_silence_sec 秒の無音を置く。最後の文の後に tail_silence_sec 秒の無音を追加する（流し終えた後も無音を流し続けたいとき）。
    """
    # 1. 最初に無音を置き、1 文ずつ読み上げて前後の無音を削り、文の前に決めた長さの無音を挟んで並べる（文の終わりの位置を控える）
    pieces: list[np.ndarray] = [np.zeros(round(SAMPLE_RATE * lead_silence_sec), dtype=np.int16)]
    position = len(pieces[0])
    ends_sec: list[float] = []
    for index, (text, gap_before_sec) in enumerate(items):
        spoken = _trim_silence(read_wav(synthesize_speech(text, tmp_path / f"sentence{index}.wav")))
        # 2 文目以降は、前の文との間に無音を挟む
        if index > 0:
            gap = np.zeros(round(SAMPLE_RATE * gap_before_sec), dtype=np.int16)
            pieces.append(gap)
            position += len(gap)
        pieces.append(spoken)
        position += len(spoken)
        ends_sec.append(position / SAMPLE_RATE)

    # 2. 最後の文の後に流し続ける無音を追加して 1 本につなぐ
    pieces.append(np.zeros(round(SAMPLE_RATE * tail_silence_sec), dtype=np.int16))
    return WavInput(np.concatenate(pieces), realtime=True, sentence_ends_sec=tuple(ends_sec))


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
    """録音の入力（マイクの入力を開く関数）の代わり。開かれると WAV の音を流し、開かれた回数と流した長さを覚える。"""

    def __init__(
        self,
        samples: np.ndarray,
        *,
        realtime: bool = False,
        sentence_ends_sec: tuple[float, ...] = (),
    ) -> None:
        self.samples = samples
        self.realtime = realtime
        self.sentence_ends_sec = sentence_ends_sec
        """文ごとの、WAV の先頭からその文を読み終える位置（秒）。文を並べて作った WAV だけが持つ。"""
        self.open_count = 0
        self._last_stream: _InputStream | None = None
        self._fed_frames = 0

    def __call__(self, on_frames: Callable[[np.ndarray], None]) -> _InputStream:
        """入力を開く。realtime ならスレッドで実時間で、そうでなければ開く中で全ての音を渡す。"""
        self.open_count += 1
        self._fed_frames = 0
        stream = _InputStream()
        self._last_stream = stream

        def counted(chunk: np.ndarray) -> None:
            """渡した長さを数えて、録音機へ音を渡す。"""
            self._fed_frames += len(chunk)
            on_frames(chunk)

        if self.realtime:
            stream.feed_in_realtime(self.samples, counted)
        else:
            for chunk in _chunks(self.samples):
                counted(chunk)
            stream.finished.set()
        return stream

    @property
    def fed_sec(self) -> float:
        """最後に入力を開いてから、録音機へ音を渡した長さ（秒）。"""
        return self._fed_frames / SAMPLE_RATE

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
    """貼り付けのキーと Enter の送信の代わり。キーを送信せずに、押された回数と Enter に添えた修飾キーを控える。"""

    pasted: list[str] = field(default_factory=list)
    enters: int = 0
    enter_modifiers: list[tuple[EnterModifier, ...]] = field(default_factory=list)  # Enter ごとに受けた修飾キーの並び

    def send_paste(self, paste_key: str) -> None:
        """貼り付けのキーが押されたことを控える。"""
        self.pasted.append(paste_key)

    def send_enter(self, modifiers: Sequence[EnterModifier] = ()) -> None:
        """Enter が押されたことと、一緒に押す修飾キーの並びを控える。"""
        self.enters += 1
        self.enter_modifiers.append(tuple(modifiers))


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


@dataclass(frozen=True)
class TranscribedAudio:
    """文字起こしに渡された録音のパスと、渡された時点でファイルがあったか。"""

    path: Path
    existed: bool


def spy_on_transcribed_audio(monkeypatch: pytest.MonkeyPatch) -> list[TranscribedAudio]:
    """文字起こしに渡された録音のパスと、その時点でファイルがあったかを、渡されるたびに控える（起こすのは本物）。"""
    transcribed: list[TranscribedAudio] = []
    original = main_module.transcribe

    def _transcribe(audio_path: Path, on_progress: Any = None, **options: Any) -> str:
        """録音を控えてから、本物で起こす。"""
        transcribed.append(TranscribedAudio(path=audio_path, existed=audio_path.exists()))
        return original(audio_path, on_progress, **options)

    monkeypatch.setattr(main_module, "transcribe", _transcribe)
    return transcribed


class StubTranscription:
    """文字起こしを、決めた文を返す（または失敗する）関数に差し替えたものの控え。受けた音声のパスを覚え、放すまで待たせることもできる。"""

    def __init__(self, text: str = "") -> None:
        self.text = text
        """返す文。"""
        self.error: Exception | None = None
        """送出する例外。None なら文を返す。"""
        self.paths: list[Path] = []
        """渡された音声のパス（渡された順）。"""
        self.progress_points: list[float] = []
        """起こす途中で知らせる進み（区間の終わりの時刻 ÷ 音声の秒数）。"""
        self.release = threading.Event()
        """放すまで戻らないための合図。既定は放した状態。"""
        self.release.set()

    def hold(self) -> None:
        """放すまで文字起こしを戻さない状態にする。"""
        self.release.clear()

    def __call__(self, audio_path: Path, on_progress: Any = None, **options: Any) -> str:
        """音声のパスを覚え、進みを知らせ、放されるまで待ってから、文を返すか例外を送出する。"""
        self.paths.append(audio_path)
        for point in self.progress_points:
            if on_progress is not None:
                on_progress(point, 1.0)
        self.release.wait(timeout=HOLD_TIMEOUT_SEC)
        if self.error is not None:
            raise self.error
        return self.text


def stub_transcription(monkeypatch: pytest.MonkeyPatch, text: str = "") -> StubTranscription:
    """文字起こしを StubTranscription に差し替える（配線の前に呼ぶ。文字起こしワーカーは起動のまま使わない）。"""
    stub = StubTranscription(text)
    monkeypatch.setattr(main_module, "transcribe", stub)
    return stub


def fail_transcription_of_segment(monkeypatch: pytest.MonkeyPatch, segment_number: int) -> None:
    """連続録音の通し番号 segment_number の区間だけ文字起こしに失敗させる（ほかの区間は本物で起こす）。"""
    original = main_module.transcribe

    def _transcribe(audio_path: Path, on_progress: Any = None, **options: Any) -> str:
        """区間の録音の名前の末尾が通し番号なので、対象の区間なら失敗させ、ほかは本物で起こす。"""
        if audio_path.stem.endswith(f"_{segment_number}"):
            raise TranscriptionError(f"区間 {segment_number} の文字起こしに失敗させた")
        return original(audio_path, on_progress, **options)

    monkeypatch.setattr(main_module, "transcribe", _transcribe)


# === ブラウザが送信する音声 ===


def encode_audio(wav_path: Path, container: str) -> bytes:
    """WAV を container（`webm`・`mp3`・`mp4`・`ogg`）の音声に書き直して、そのバイト列を返す。"""
    import av

    codec, rate, options = {
        "webm": ("libopus", 48000, {}),
        "mp3": ("libmp3lame", 44100, {}),
        "ogg": ("libopus", 48000, {}),
        "mp4": ("aac", 44100, {"movflags": "frag_keyframe+empty_moov+default_base_moof"}),
    }[container]
    target = wav_path.with_suffix(f".encoded.{container}")
    with (
        av.open(str(wav_path)) as source,
        av.open(str(target), "w", format=container, options=options) as destination,
    ):
        stream = destination.add_stream(codec, rate=rate)
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=stream.rate)
        for frame in source.decode(audio=0):
            for resampled in resampler.resample(frame):
                destination.mux(stream.encode(resampled))
        for resampled in resampler.resample(None):
            destination.mux(stream.encode(resampled))
        destination.mux(stream.encode(None))
    return target.read_bytes()


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
    outputs = (
        [default_output("paste_and_send")]
        if only_paste_and_send
        else load_test_default_settings().outputs
    )
    local_whisper = {} if vad_threshold is None else {"vad_threshold": vad_threshold}
    settings = make_test_settings(
        {"transcription": {"local_whisper": local_whisper}}, outputs=outputs
    )
    if continuous_session_limit_sec is None:
        return settings
    # 連続録音のセッションの上限時間は、検査を通さずに入れる
    continuous = settings.api.continuous.model_copy(
        update={"session_limit_sec": continuous_session_limit_sec}
    )
    api = settings.api.model_copy(update={"continuous": continuous})
    return settings.model_copy(update={"api": api})


FIRST_PRESET_NAME = "既定"
"""用語集のプリセットの 1 つ目の名前（設定で選んでいるプリセット）。"""

SECOND_PRESET_NAME = "別"
"""用語集のプリセットの 2 つ目の名前。"""

FIRST_PRESET_CORRECTED_WORD = "試験"
"""1 つ目のプリセットの用語集が、SPEECH_WORD を置き換える正しい表記。"""

SECOND_PRESET_CORRECTED_WORD = "THIS"
"""2 つ目のプリセットの用語集が、SPEECH_TEXT の「これ」を置き換える正しい表記。"""


def make_glossary_preset_settings(tmp_path: Path) -> Settings:
    """用語集のプリセットを 2 つ持つ設定を作る。

    2 つのプリセットはそれぞれ別の用語集を使い、書き出した文（SPEECH_TEXT）の別々の言葉を置き換える行を 1 つずつ持つ。
    設定で選んでいるのは 1 つ目の FIRST_PRESET_NAME。
    """
    first_csv = tmp_path / "first.csv"
    second_csv = tmp_path / "second.csv"
    first_csv.write_text(f"誤変換,正しい表記\n{SPEECH_WORD},{FIRST_PRESET_CORRECTED_WORD}\n", encoding="utf-8")
    second_csv.write_text(f"誤変換,正しい表記\nこれ,{SECOND_PRESET_CORRECTED_WORD}\n", encoding="utf-8")
    return make_settings(only_paste_and_send=True).model_copy(
        update={
            "glossaries": [
                GlossarySettings(name="first", path=first_csv),
                GlossarySettings(name="second", path=second_csv),
            ],
            "glossary_presets": [
                GlossaryPresetSettings(name=FIRST_PRESET_NAME, glossaries=["first"]),
                GlossaryPresetSettings(name=SECOND_PRESET_NAME, glossaries=["second"]),
            ],
            "active_glossary_preset": FIRST_PRESET_NAME,
        }
    )


def spy_on_correct_presets(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """補正を、受けた用語集のプリセットの名前（None は指定なし）を控えて文をそのまま返す関数に差し替える（配線の前でも後でもよい）。"""
    presets: list[str | None] = []

    def _correct(text: str, glossary_preset: str | None, **_options: Any) -> str:
        """プリセットの名前を控え、文を補正せずに返す。"""
        presets.append(glossary_preset)
        return text

    monkeypatch.setattr(main_module, "_correct", _correct)
    return presets


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
    port: int

    @property
    def web_origin(self) -> str:
        """ブラウザが `/web/` を localhost で開いたときの Origin（`http://localhost:{ポート}`）。"""
        return f"http://localhost:{self.port}"

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
        self, callback_url: str, *, continuous: bool = False, glossary_preset: str | None = None
    ) -> tuple[httpx.Response, float]:
        """API の開始（continuous なら連続録音。glossary_preset があれば用語集のプリセットを指定）を呼び、応答と、応答までにかかったミリ秒を返す。"""
        started = time.perf_counter()
        body: dict[str, object] = {"callback_url": callback_url}
        # 連続録音のときだけ continuous を指定する（指定しない開始は 1 回の録音）
        if continuous:
            body["continuous"] = True
        # 用語集のプリセットを指定するときだけ glossary_preset を指定する（指定しない開始は設定で選んでいるプリセット）
        if glossary_preset is not None:
            body["glossary_preset"] = glossary_preset
        response = self.post("/sessions", json_body=body)
        return response, (time.perf_counter() - started) * 1000

    def web_headers(self, **extra: str) -> dict[str, str]:
        """ゲートウェイを通した構成の `/web/` の要求のヘッダー（Host は localhost:{ポート}、トークン無し）に extra を追加する。"""
        return {"Host": f"localhost:{self.port}", **extra}

    def post_web_audio(
        self,
        data: bytes,
        *,
        origin: str | None = None,
        filename: str = "recording.webm",
        glossary_preset: str | None = None,
    ) -> httpx.Response:
        """音声を multipart の audio で POST /web/transcriptions へ送信する。origin が None なら画面と同じオリジンで送信し、glossary_preset があれば用語集のプリセットの名前を一緒に送信する。"""
        headers = self.web_headers(Origin=self.web_origin if origin is None else origin)
        form = None if glossary_preset is None else {"glossary_preset": glossary_preset}
        return self.http.post(
            "/web/transcriptions",
            files={"audio": (filename, data, "audio/webm")},
            data=form,
            headers=headers,
        )

    def post_web_body(self, body: bytes, *, chunked: bool = False) -> httpx.Response:
        """sized_multipart_body で作った本文を POST /web/transcriptions へ送信する（画面と同じオリジン）。chunked なら Content-Length を付けずに送信する。"""
        headers = self.web_headers(Origin=self.web_origin, **{"Content-Type": CONTENT_TYPE})
        return self.http.post(
            "/web/transcriptions",
            content=chunks_of(body) if chunked else body,
            headers=headers,
            timeout=LARGE_BODY_TIMEOUT_SEC,
        )

    def get_job(self, job_id: str) -> httpx.Response:
        """GET /web/transcriptions/{job_id} を呼ぶ。"""
        return self.http.get(f"/web/transcriptions/{job_id}", headers=self.web_headers())

    def close(self) -> None:
        """クライアントを閉じて待ち受けを止める。"""
        self.http.close()
        self.runner.stop()


def serve_api(
    session_api: SessionApiDeps,
    web_api: WebApiDeps | None,
    allowed_web_origins: Sequence[str] | Callable[[int], Sequence[str]] = (),
    port: int | None = None,
) -> InProcessApi:
    """build_fastapi で組み立てた app を 127.0.0.1 の空きポートで待ち受けさせ、叩くクライアントを返す。

    許す Origin は、一覧か、決まったポートから一覧を作る関数で渡す（ブラウザの Origin はポートを含むため）。
    """
    token = create_token()
    port = free_port() if port is None else port
    origins = allowed_web_origins(port) if callable(allowed_web_origins) else allowed_web_origins
    app = build_fastapi(session_api, token, port, web_api=web_api, allowed_web_origins=origins)
    runner = ApiServerRunner(app, port)
    assert runner.start(API_START_TIMEOUT_SEC)
    http = httpx.Client(base_url=f"http://{LOOPBACK}:{port}", timeout=REQUEST_TIMEOUT_SEC)
    return InProcessApi(runner=runner, http=http, token=token.get_secret_value(), port=port)


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

    def web_temp_files(self) -> list[Path]:
        """ブラウザの音声の一時のフォルダに残っているファイルを返す（フォルダが無ければ空）。"""
        tmp_dir = self.handlers.web_api.tmp_dir
        return sorted(tmp_dir.iterdir()) if tmp_dir.exists() else []

    def history_files(self, suffix: str) -> list[Path]:
        """履歴に残ったファイルのうち、拡張子が suffix のものを返す。"""
        return sorted(self.paths.history_dir.rglob(f"*{suffix}"))

    def start_api(self) -> InProcessApi:
        """build_fastapi で組み立てた app を 127.0.0.1 の空きポートで待ち受けさせ、叩くクライアントを返す。"""
        self.api = serve_api(
            self.handlers.session_api,
            self.handlers.web_api,
            self.handlers.settings_store.get().api.allowed_web_origins,
        )
        return self.api

    def start_web_api(
        self, *, allowed: bool = True, port: int | None = None, start_queue: bool = True
    ) -> InProcessApi:
        """ブラウザの音声のキューを始め、localhost で開く `/web/` の Origin を許して API を待ち受けさせる。

        allowed が偽なら、どの Origin も許さない。port を渡すと、そのポートで待ち受ける（止めた API を同じポートで立て直す）。
        start_queue が偽なら、キューは始めない（立て直しでワーカースレッドを重ねない）。
        """
        web_api = self.handlers.web_api
        if start_queue:
            web_api.queue.start(web_api.tmp_dir)
        self.api = serve_api(
            self.handlers.session_api,
            web_api,
            (lambda chosen: [f"http://localhost:{chosen}"]) if allowed else (),
            port,
        )
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
        # ブラウザの文字起こしを配線した OS か（Linux は配線しない）
        if self.handlers.web_api is not None:
            # した: ブラウザの音声のキューを閉じる
            self.handlers.web_api.queue.close()
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
    paths = resolve_app_paths(tmp_path)
    # OS ごとの実装は本物を選び、システム音量・貼り付けのキー・Enter だけ呼ばれた値を控えるものに差し替えて渡す
    adapters = replace(
        main_module.select_platform_adapters(
            CURRENT_OS,
            lock_file=paths.lock_file,
            display_session=detect_display_session(os.environ),
        ),
        lower_volume=volume.lower,
        restore_volume=volume.restore,
        send_paste=keys.send_paste,
        send_enter=keys.send_enter,
    )
    handlers = main_module.build_handlers(
        settings,
        paths,
        notifications,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: None,
        adapters=adapters,
        environ=os.environ,
        unavailable=unavailable_features(CURRENT_OS),
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


def worker_process_pids() -> set[int]:
    """文字起こしワーカーのプロセス（ランチャーと本体）の番号を返す。"""
    return {worker.pid for worker in worker_processes()}


def worker_ready_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """文字起こしワーカーが ready になったときのログの文（立て直しを含む）を、控えたログから順に返す。

    テストは先に `caplog.set_level(logging.INFO, logger=WORKER_CLIENT_LOGGER)` を呼んでから配線する。
    """
    return [
        record.getMessage() for record in caplog.records if WORKER_READY_LOG in record.getMessage()
    ]


class _ProcessEntry(ctypes.Structure):
    """Toolhelp のプロセスの 1 行（PROCESSENTRY32W）。"""

    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * TOOLHELP_EXE_FILE_CHARS),
    )


def process_tree_pids(root_pid: int) -> set[int]:
    """root_pid とその子孫のプロセスの番号を直ちに引いて返す。

    Windows は Toolhelp のスナップショットで引く（PowerShell の一覧は数秒かかる）。Linux は /proc から引く。
    """
    # Windows か
    if CURRENT_OS != OsKind.WINDOWS:
        # 違う: /proc の一覧から子孫を辿る
        return {process.pid for process in descendants(root_pid)}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(TOOLHELP_SNAPSHOT_PROCESS, 0)
    parents: dict[int, int] = {}
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(_ProcessEntry)
    try:
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    tree = {root_pid}
    # 親が tree に入っているプロセスを、増えなくなるまで追加する
    grown = True
    while grown:
        children = {pid for pid, parent in parents.items() if parent in tree} - tree
        tree |= children
        grown = bool(children)
    return tree


def kill_one_worker(pids: Iterable[int]) -> bool:
    """番号のプロセス（ワーカーのランチャーと本体）を止め、止める番号があったかを返す。

    プロセスの一覧は引かない（一覧を引く間に文字起こしが終わるため、番号は止める時刻より前に引いておく）。
    taskkill も使わない（子孫を探すために数秒かかる）。Windows では os.kill が番号のプロセスを直ちに終わらせる。
    """
    targets = list(pids)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            # 先に止めたランチャーとともに既に終わっているプロセス
            continue
    return bool(targets)


def kill_workers_twice(
    first_pids: Iterable[int], ready_messages: Callable[[], list[str]]
) -> int:
    """引いておいた番号のワーカーを止め、やり直しに立ったワーカーも ready になった直後に止める。止めた回数を返す。

    first_pids は止める時刻より前に引いた、1 回目に止めるワーカーの番号。
    ready_messages は ready になったときのログの文を順に返す関数。
    """
    # 1. 立ち上がっているワーカーを止める（窓口が落ちたことに気づいて立て直す）
    ready_before = len(ready_messages())
    kills = int(kill_one_worker(first_pids))

    # 2. やり直しのワーカーが ready になるのを待つ（読み込みの途中で止めると、やり直しの前に失敗する）
    deadline = time.monotonic() + WORKER_READY_TIMEOUT_SEC
    while len(ready_messages()) <= ready_before:
        assert time.monotonic() < deadline, "やり直しのワーカーが ready にならなかった"
        time.sleep(WORKER_READY_POLL_SEC)

    # 3. ready のログに書かれたランチャーの番号から、一覧を引かずに子孫ごと止める
    match = READY_PID_PATTERN.search(ready_messages()[-1])
    assert match is not None, "ready のログにワーカーの番号が無い"
    return kills + int(kill_one_worker(process_tree_pids(int(match.group(1)))))
