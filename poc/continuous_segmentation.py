"""PoC: 録音を止めずに Silero VAD で区切り、区間ごとの文字起こしが話す速さに追いつくかを確かめる。

SAPI で読み上げた WAV を、長さの揃わないブロックで実時間で流す。
入力のコールバックを模したスレッドから区切りのスレッドへ渡し、512 サンプルに組み直して
Silero VAD を状態（h・c・前の 64 サンプル）を持ち越しながら流す。
区切った区間は待ち行列へ積み、今の文字起こしワーカー（WhisperWorkerClient）で区切った順に起こす。
同じプロセスで uvicorn の API サーバーを立て、要求を送り続けて GIL を取り合わせる。

実行（リポジトリの直下で）:
    venv/Scripts/python.exe poc/continuous_segmentation.py
"""

from __future__ import annotations

import json
import queue
import random
import statistics
import sys
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
import win32com.client  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from faster_whisper.vad import VadOptions, get_speech_timestamps, get_vad_model  # noqa: E402
from scipy.io import wavfile  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

from voice_paste.integrations.whisper.client import WhisperWorkerClient  # noqa: E402
from voice_paste.shared.settings import LocalWhisperSettings  # noqa: E402

# === 定数 ===

SAMPLE_RATE = 16000
"""録音の標本化周波数（常駐アプリと同じ）。"""

VAD_WINDOW = 512
"""Silero VAD に 1 回で渡すサンプル数（16 kHz で 32 ms）。"""

VAD_CONTEXT = 64
"""Silero VAD が前の窓から持ち越す文脈のサンプル数。"""

VAD_STATE_SHAPE = (1, 1, 128)
"""Silero VAD の LSTM の状態 h・c の形。"""

SPEECH_THRESHOLD = 0.5
"""話し声と判定する確率（faster-whisper の VadOptions の既定と同じ）。"""

NEG_THRESHOLD = SPEECH_THRESHOLD - 0.15
"""話し声の終わりと判定する確率（faster-whisper の既定の決め方と同じ）。"""

MIN_SILENCE_SEC = 2.0
"""区切る無音の長さ（今の vad_min_silence_ms の既定）。"""

MAX_SEGMENT_SEC = 30.0
"""区間の最大の長さ（PoC の仮の値）。"""

SHORT_SILENCE_SEC = 0.098
"""最大の長さで区切るときに、区切り目として使える短い無音の長さ（faster-whisper と同じ）。"""

SEGMENT_PAD_SEC = 0.3
"""区間の前後に付ける余白。"""

BLOCK_MIN = 160
"""入力のコールバックに届くブロックの最小のサンプル数。"""

BLOCK_MAX = 1024
"""入力のコールバックに届くブロックの最大のサンプル数。"""

TRIM_RATIO = 0.01
"""読み上げの前後の無音を削る振幅の閾値（最大振幅に対する比）。"""

GAP_FRAME_SEC = 0.01
"""話し声の間を測るときの枠の長さ。"""

MIN_GAP_SEC = 0.3
"""話し声の間として数える最短の長さ（文の中の息継ぎを数えない）。"""

GAP_TOLERANCE_SEC = 0.05
"""狙った話し声の間とのずれの許容。"""

LEAD_SILENCE_SEC = 1.0
"""場面の頭と尻に足す無音。"""

PACKED_GAP_SEC = 2.1
"""区切りの無音をわずかに超える話し声の間。"""

JOINED_GAP_SEC = 1.0
"""区切ってはいけない話し声の間。"""

LONG_SPEECH_MIN_SEC = 45.0
"""「話し続ける」の読み上げの最短の長さ。"""

SNR_DB = 10.0
"""背景音の読み上げに対する比。"""

BOUNDARY_TOLERANCE_SEC = 0.5
"""一度に渡した区間との境目の時刻の差の許容。"""

CER_TOLERANCE = 0.02
"""区間をつないだ文字と 1 回の録音で起こした文字の文字誤り率の差の許容。"""

LATENCY_LIMIT_SEC = 3.0
"""区切ってから区間の文字が出るまでの時間の上限。"""

QUEUE_LIMIT = 1
"""待ち行列の長さの上限。"""

API_LOAD_INTERVAL_SEC = 0.02
"""同じプロセスの API サーバーへ要求を送る間隔。"""

WORKER_READY_TIMEOUT_SEC = 120.0
"""文字起こしワーカーの起動を待つ上限（PoC ではモデルの読み込みを含めて長めに待つ）。"""

WORKER_STOP_TIMEOUT_SEC = 5.0
"""文字起こしワーカーの終わりを待つ上限。"""

SAPI_CREATE_FOR_WRITE = 3
"""SAPI の出力のファイルを書き込み用に作るモード。"""

SAPI_IS_XML = 8
"""SAPI の Speak に XML を渡すフラグ。"""

BACKGROUND_PITCH = -10
"""背景の声の高さ（SAPI XML の absmiddle）。本来の読み上げと声を変えるため下げる。"""

SENTENCES = (
    "今日はいい天気ですね。",
    "午後から会議の資料をまとめます。",
    "新しいゲームの発売日が近づいてきました。",
    "このボスは右側から攻撃すると倒しやすいです。",
    "少し休憩してからもう一度挑戦します。",
    "配信を見てくれてありがとうございます。",
)
"""場面で読み上げる文。"""

LONG_PARAGRAPH = (
    "ここからは少し長めに話し続けます。"
    "最初のステージは森の中にあって、敵の数はそれほど多くありません。"
    "ただし木の陰から急に飛び出してくる敵がいるので、周りをよく見ながら進む必要があります。"
    "途中で回復のアイテムを拾えるので、体力が減っていても焦らずに進めば大丈夫です。"
    "森を抜けると大きな橋があり、その先に最初のボスが待っています。"
    "ボスは三回攻撃したあとに隙ができるので、そのタイミングで近づいて攻撃します。"
    "慣れてくると攻撃を避けながら反撃できるようになるので、何度か挑戦してみてください。"
    "次のステージは洞窟で、暗くて道が分かりにくいので地図を見ながら進みます。"
)
"""「話し続ける」で 1 回で読み上げる文章。"""

BACKGROUND_LINES = (
    "敵が近づいてきたぞ、気をつけろ。",
    "こっちの道は行き止まりだ、引き返そう。",
    "宝箱を見つけた、中を確かめてみよう。",
    "時間がない、急いで先へ進むんだ。",
)
"""「背景音（人の声）」で別の声に読ませる台詞。"""


# === 入力の作成 ===


def synthesize(text: str, out_dir: Path, *, xml: bool = False) -> np.ndarray:
    """SAPI の日本語の声で text を読み上げ、16 kHz の float32 の音を返す。"""
    raw_path = out_dir / f"sapi_{time.perf_counter_ns()}.wav"
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Open(str(raw_path), SAPI_CREATE_FOR_WRITE)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Speak(text, SAPI_IS_XML if xml else 0)
    stream.Close()

    rate, samples = wavfile.read(raw_path)
    raw_path.unlink()
    divisor = np.gcd(SAMPLE_RATE, rate)
    resampled = resample_poly(samples.astype(np.float32), SAMPLE_RATE // divisor, rate // divisor)
    return (resampled / np.iinfo(np.int16).max).astype(np.float32)


def trim(audio: np.ndarray) -> np.ndarray:
    """前後の無音を最大振幅の TRIM_RATIO で削る。"""
    loud = np.flatnonzero(np.abs(audio) >= np.abs(audio).max() * TRIM_RATIO)
    return audio[loud[0] : loud[-1] + 1]


def silence(seconds: float) -> np.ndarray:
    """seconds 秒の無音を返す。"""
    return np.zeros(round(seconds * SAMPLE_RATE), dtype=np.float32)


def join(parts: list[np.ndarray], gaps: list[float]) -> np.ndarray:
    """話し声の間に gaps の長さの無音を挟んでつなぎ、頭と尻に無音を足す。"""
    pieces = [silence(LEAD_SILENCE_SEC)]
    for index, part in enumerate(parts):
        pieces.append(part)
        # 最後の部品の後ろだけ、間の代わりに尻の無音を足す
        pieces.append(silence(gaps[index] if index < len(gaps) else LEAD_SILENCE_SEC))
    return np.concatenate(pieces)


def measure_gaps(audio: np.ndarray, reference_peak: float) -> list[float]:
    """話し声の間（MIN_GAP_SEC 以上の静かな枠の続き）の長さを、頭と尻を除いて返す。"""
    frame = round(GAP_FRAME_SEC * SAMPLE_RATE)
    frames = audio[: len(audio) // frame * frame].reshape(-1, frame)
    loud = np.abs(frames).max(axis=1) >= reference_peak * TRIM_RATIO
    gaps: list[float] = []
    run = 0
    seen_speech = False
    for is_loud in loud:
        # 話し声の枠: それまでの静かな続きが十分長ければ間として数える
        if is_loud:
            if seen_speech and run * GAP_FRAME_SEC >= MIN_GAP_SEC:
                gaps.append(round(run * GAP_FRAME_SEC, 2))
            seen_speech = True
            run = 0
        else:
            run += 1
    return gaps


def pink_noise(length: int, rng: np.random.Generator) -> np.ndarray:
    """1/f のスペクトルを持つノイズを返す。"""
    spectrum = np.fft.rfft(rng.standard_normal(length))
    freqs = np.fft.rfftfreq(length)
    freqs[0] = freqs[1]
    noise = np.fft.irfft(spectrum / np.sqrt(freqs), n=length)
    return (noise / np.abs(noise).max()).astype(np.float32)


def speech_rms(audio: np.ndarray, reference_peak: float) -> float:
    """話し声の枠だけの二乗平均平方根を返す。"""
    frame = round(GAP_FRAME_SEC * SAMPLE_RATE)
    frames = audio[: len(audio) // frame * frame].reshape(-1, frame)
    loud = frames[np.abs(frames).max(axis=1) >= reference_peak * TRIM_RATIO]
    return float(np.sqrt(np.mean(loud**2)))


def mix(speech: np.ndarray, background: np.ndarray, reference_peak: float) -> np.ndarray:
    """背景音を話し声に対して SNR_DB になる大きさで重ねる。"""
    target_rms = speech_rms(speech, reference_peak) / (10 ** (SNR_DB / 20))
    background = np.resize(background, len(speech))
    scaled = background * (target_rms / float(np.sqrt(np.mean(background**2))))
    return np.clip(speech + scaled, -1.0, 1.0).astype(np.float32)


@dataclass(frozen=True, slots=True, kw_only=True)
class Scene:
    """流す場面。"""

    name: str
    audio: np.ndarray
    script: str
    expected_segments: int | None
    target_gaps: list[float]
    check_boundaries: bool
    check_cer: bool
    check_latency: bool


def build_scenes(work_dir: Path) -> tuple[list[Scene], float]:
    """入力の場面と、読み上げの最大振幅を返す。"""
    rng = np.random.default_rng(0)
    sentences = [trim(synthesize(text, work_dir)) for text in SENTENCES]
    peak = max(float(np.abs(s).max()) for s in sentences)

    # 詰めて続ける: 6 文を 2.1 秒の間で続ける
    packed_gaps = [PACKED_GAP_SEC] * (len(sentences) - 1)
    packed = join(sentences, packed_gaps)

    # 区切らない間: 2 文ずつ 1.0 秒でつないだ組を 3 組、組の間は 2.1 秒
    pair_gaps = [JOINED_GAP_SEC, PACKED_GAP_SEC, JOINED_GAP_SEC, PACKED_GAP_SEC, JOINED_GAP_SEC]
    paired = join(sentences, pair_gaps)

    # 話し続ける: 1 回の読み上げで LONG_SPEECH_MIN_SEC 以上読み続ける
    paragraph = LONG_PARAGRAPH
    long_speech = trim(synthesize(paragraph, work_dir))
    while len(long_speech) / SAMPLE_RATE < LONG_SPEECH_MIN_SEC:
        paragraph += LONG_PARAGRAPH
        long_speech = trim(synthesize(paragraph, work_dir))
    continuous = join([long_speech], [])

    # 背景音: ピンクノイズと、高さを変えた別の声の台詞
    noisy = mix(packed, pink_noise(len(packed), rng), peak)
    lines = "".join(
        f'<pitch absmiddle="{BACKGROUND_PITCH}">{line}</pitch><silence msec="700"/>'
        for line in BACKGROUND_LINES
    )
    background_voice = synthesize(lines, work_dir, xml=True)
    voiced = mix(packed, background_voice, peak)

    packed_script = "".join(SENTENCES)
    return [
        Scene(name="詰めて続ける", audio=packed, script=packed_script, expected_segments=6,
              target_gaps=packed_gaps, check_boundaries=True, check_cer=True, check_latency=True),
        Scene(name="区切らない間", audio=paired, script=packed_script, expected_segments=3,
              target_gaps=pair_gaps, check_boundaries=True, check_cer=True, check_latency=False),
        Scene(name="話し続ける", audio=continuous, script=paragraph, expected_segments=2,
              target_gaps=[], check_boundaries=False, check_cer=True, check_latency=True),
        Scene(name="背景音（ノイズ）", audio=noisy, script=packed_script, expected_segments=6,
              target_gaps=[], check_boundaries=False, check_cer=False, check_latency=False),
        Scene(name="背景音（人の声）", audio=voiced, script=packed_script, expected_segments=None,
              target_gaps=[], check_boundaries=False, check_cer=False, check_latency=False),
    ], peak


# === 区切り ===


@dataclass(slots=True)
class StreamingVad:
    """Silero VAD を 512 サンプルずつ、h・c・前の 64 サンプルを持ち越して流す。"""

    session: object
    h: np.ndarray = field(default_factory=lambda: np.zeros(VAD_STATE_SHAPE, dtype=np.float32))
    c: np.ndarray = field(default_factory=lambda: np.zeros(VAD_STATE_SHAPE, dtype=np.float32))
    context: np.ndarray = field(default_factory=lambda: np.zeros(VAD_CONTEXT, dtype=np.float32))

    def __call__(self, window: np.ndarray) -> float:
        """1 窓の話し声の確率を返す。"""
        batch = np.concatenate([self.context, window])[np.newaxis, :]
        output, self.h, self.c = self.session.run(None, {"input": batch, "h": self.h, "c": self.c})
        self.context = window[-VAD_CONTEXT:]
        return float(output.reshape(-1)[0])


@dataclass(frozen=True, slots=True, kw_only=True)
class Segment:
    """区切った区間。"""

    index: int
    start: int
    end: int
    speech_start: int
    speech_end: int
    reason: str
    emitted_at: float


@dataclass(slots=True)
class Segmenter:
    """窓ごとの確率から区間を切り出す。録音は止めず、区切りは窓の位置で決める。"""

    vad: StreamingVad
    on_segment: object
    recording: list[np.ndarray] = field(default_factory=list)
    pending: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    position: int = 0
    triggered: bool = False
    speech_start: int = 0
    temp_end: int = 0
    last_short_silence: int = 0
    previous_cut: int = 0
    count: int = 0
    vad_times: list[float] = field(default_factory=list)

    def feed(self, block: np.ndarray) -> None:
        """ブロックを受け取り、512 サンプルに組み直して窓ごとに判定する。"""
        self.recording.append(block)
        self.pending = np.concatenate([self.pending, block])
        while len(self.pending) >= VAD_WINDOW:
            window, self.pending = self.pending[:VAD_WINDOW], self.pending[VAD_WINDOW:]
            started = time.perf_counter()
            prob = self.vad(window)
            self.vad_times.append(time.perf_counter() - started)
            self._step(prob)
            self.position += VAD_WINDOW

    def _step(self, prob: float) -> None:
        """1 窓の確率で状態を進め、区切りが決まれば区間を出す。"""
        min_silence = MIN_SILENCE_SEC * SAMPLE_RATE
        # 話し声を検出: 続いている無音の候補を取り消す
        if prob >= SPEECH_THRESHOLD and self.temp_end:
            self.temp_end = 0
        # 話し声が始まった
        if prob >= SPEECH_THRESHOLD and not self.triggered:
            self.triggered = True
            self.speech_start = self.position
            self.last_short_silence = 0
            return
        if not self.triggered:
            return
        # 区間が最大の長さに達した: 直近の短い無音か今の位置で区切る
        if self.position - self.speech_start >= MAX_SEGMENT_SEC * SAMPLE_RATE:
            cut = self.last_short_silence or self.position
            self._emit(cut, cut, "最大の長さ")
            self.speech_start = cut
            self.last_short_silence = 0
            self.temp_end = 0
            return
        # 話し声の終わりの候補: 無音が続いた長さで判断する
        if prob < NEG_THRESHOLD:
            if not self.temp_end:
                self.temp_end = self.position
            silent = self.position - self.temp_end
            if silent >= SHORT_SILENCE_SEC * SAMPLE_RATE:
                self.last_short_silence = self.temp_end + silent // 2
            if silent >= min_silence:
                pad = round(SEGMENT_PAD_SEC * SAMPLE_RATE)
                self._emit(self.temp_end + pad, self.temp_end, "無音")
                self.triggered = False
                self.temp_end = 0

    def _emit(self, cut: int, speech_end: int, reason: str) -> None:
        """前の区切りから cut までを区間として出す。頭の無音は余白を残して落とす。"""
        pad = round(SEGMENT_PAD_SEC * SAMPLE_RATE)
        start = max(self.previous_cut, self.speech_start - pad)
        self.count += 1
        self.on_segment(Segment(index=self.count, start=start, end=cut,
                                speech_start=self.speech_start, speech_end=speech_end,
                                reason=reason, emitted_at=time.perf_counter()))
        self.previous_cut = cut

    def flush(self) -> None:
        """完了: 話し声の途中なら、そこまでを最後の区間として出す。"""
        if self.triggered:
            self._emit(self.position, self.temp_end or self.position, "完了")
            self.triggered = False

    def audio(self) -> np.ndarray:
        """ここまでの録音を返す。"""
        return np.concatenate(self.recording)


# === 同じプロセスの API サーバー ===


def start_api_load(stop: threading.Event) -> list[threading.Thread]:
    """同じプロセスに uvicorn の API サーバーを立て、要求を送り続けるスレッドを立てる。"""
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """疎通を返す。"""
        return {"status": "ok"}

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    while not server.started:
        time.sleep(API_LOAD_INTERVAL_SEC)
    port = server.servers[0].sockets[0].getsockname()[1]

    def hammer() -> None:
        """止めるまで API サーバーへ要求を送る。"""
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            while not stop.is_set():
                client.get("/ping")
                time.sleep(API_LOAD_INTERVAL_SEC)
        server.should_exit = True

    load_thread = threading.Thread(target=hammer, daemon=True)
    load_thread.start()
    return [server_thread, load_thread]


# === 文字起こし ===


def write_wav(path: Path, audio: np.ndarray) -> Path:
    """float32 の音を 16 bit の WAV に書く。"""
    clipped = np.clip(audio, -1.0, 1.0)
    wavfile.write(path, SAMPLE_RATE, (clipped * np.iinfo(np.int16).max).astype(np.int16))
    return path


def transcribe(client: WhisperWorkerClient, audio: np.ndarray, work_dir: Path) -> str:
    """音を文字に起こす。"""
    path = write_wav(work_dir / f"seg_{time.perf_counter_ns()}.wav", audio)
    text = "".join(client.transcribe(path))
    path.unlink()
    return text


def normalize(text: str) -> str:
    """句読点・空白を除き、文字の幅を揃える。"""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in folded if not unicodedata.category(ch).startswith(("P", "Z")))


def cer(reference: str, hypothesis: str) -> float:
    """文字誤り率（編集距離 ÷ 正解の長さ）を返す。"""
    ref, hyp = normalize(reference), normalize(hypothesis)
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        current = [i]
        for j, h in enumerate(hyp, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1] / len(ref)


# === 場面の実行 ===


def run_scene(scene: Scene, client: WhisperWorkerClient, work_dir: Path, peak: float) -> dict:
    """1 場面を実時間で流し、区切り・文字起こしを測る。"""
    rng = random.Random(0)
    session = get_vad_model().session
    segments: queue.Queue[Segment | None] = queue.Queue()
    blocks: queue.Queue[np.ndarray | None] = queue.Queue()
    results: list[dict] = []
    max_queue = 0

    def on_segment(segment: Segment) -> None:
        """区切った区間を待ち行列へ積む。"""
        nonlocal max_queue
        segments.put(segment)
        max_queue = max(max_queue, segments.qsize())

    segmenter = Segmenter(vad=StreamingVad(session=session), on_segment=on_segment)

    def feed_input() -> None:
        """入力のコールバックを模して、長さの揃わないブロックを実時間で渡す。"""
        offset = 0
        started = time.perf_counter()
        while offset < len(scene.audio):
            size = rng.randint(BLOCK_MIN, BLOCK_MAX)
            blocks.put(scene.audio[offset : offset + size])
            offset += size
            # 実時間に合わせる: 次のブロックが録れる時刻まで待つ
            delay = started + offset / SAMPLE_RATE - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        blocks.put(None)

    def segment_input() -> None:
        """ブロックを区切りへ渡し、入力が終わったら完了として残りを区切る。"""
        while (block := blocks.get()) is not None:
            segmenter.feed(block)
        segmenter.flush()
        segments.put(None)

    def transcribe_segments() -> None:
        """区間を区切った順に 1 つずつ起こす。"""
        while (segment := segments.get()) is not None:
            audio = segmenter.audio()[segment.start : segment.end]
            started = time.perf_counter()
            text = transcribe(client, audio, work_dir)
            done = time.perf_counter()
            results.append({
                "index": segment.index,
                "reason": segment.reason,
                "start_sec": round(segment.start / SAMPLE_RATE, 2),
                "end_sec": round(segment.end / SAMPLE_RATE, 2),
                "speech_start_sec": round(segment.speech_start / SAMPLE_RATE, 2),
                "speech_end_sec": round(segment.speech_end / SAMPLE_RATE, 2),
                "length_sec": round((segment.end - segment.start) / SAMPLE_RATE, 2),
                "transcribe_sec": round(done - started, 2),
                "ratio": round((done - started) / ((segment.end - segment.start) / SAMPLE_RATE), 3),
                "latency_sec": round(done - segment.emitted_at, 2),
                "text": text,
            })

    threads = [threading.Thread(target=fn) for fn in (feed_input, segment_input, transcribe_segments)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # 一度に渡した区間（境目の比較の正解）
    reference = get_speech_timestamps(
        scene.audio, VadOptions(min_silence_duration_ms=round(MIN_SILENCE_SEC * 1000),
                                speech_pad_ms=0, max_speech_duration_s=MAX_SEGMENT_SEC),
    )
    ref_bounds = [(r["start"] / SAMPLE_RATE, r["end"] / SAMPLE_RATE) for r in reference]
    stream_bounds = [(r["speech_start_sec"], r["speech_end_sec"]) for r in results]
    boundary_diffs = (
        [round(max(abs(a[0] - b[0]), abs(a[1] - b[1])), 2) for a, b in zip(ref_bounds, stream_bounds, strict=True)]
        if len(ref_bounds) == len(stream_bounds) else None
    )

    whole_text = transcribe(client, scene.audio, work_dir) if scene.check_cer else ""
    joined_text = "".join(r["text"] for r in results)
    measured_gaps = measure_gaps(scene.audio, peak)

    return {
        "scene": scene.name,
        "duration_sec": round(len(scene.audio) / SAMPLE_RATE, 2),
        "target_gaps": scene.target_gaps,
        "measured_gaps": measured_gaps,
        "expected_segments": scene.expected_segments,
        "segments": results,
        "order": [r["index"] for r in results],
        "max_queue": max_queue,
        "vad_ms_mean": round(statistics.mean(segmenter.vad_times) * 1000, 3),
        "vad_ms_max": round(max(segmenter.vad_times) * 1000, 3),
        "reference_bounds": [(round(a, 2), round(b, 2)) for a, b in ref_bounds],
        "boundary_diffs": boundary_diffs,
        "check_boundaries": scene.check_boundaries,
        "check_cer": scene.check_cer,
        "check_latency": scene.check_latency,
        "cer_joined": round(cer(scene.script, joined_text), 4) if scene.check_cer else None,
        "cer_whole": round(cer(scene.script, whole_text), 4) if scene.check_cer else None,
        "joined_text": joined_text,
        "whole_text": whole_text,
    }


def judge(result: dict) -> dict[str, bool | None]:
    """成功条件ごとの合否を返す（当てない条件は None）。"""
    segments = result["segments"]
    expected = result["expected_segments"]
    gaps_ok = all(
        abs(m - t) < GAP_TOLERANCE_SEC for m, t in zip(result["measured_gaps"], result["target_gaps"], strict=False)
    ) and (not result["target_gaps"] or len(result["measured_gaps"]) == len(result["target_gaps"]))
    return {
        "間の作り": gaps_ok if result["target_gaps"] else None,
        "区切りの正しさ": None if expected is None else len(segments) == expected,
        "判定の一致": (
            result["boundary_diffs"] is not None
            and all(d <= BOUNDARY_TOLERANCE_SEC for d in result["boundary_diffs"])
        ) if result["check_boundaries"] else None,
        "境目での欠け": (
            result["cer_joined"] - result["cer_whole"] <= CER_TOLERANCE
        ) if result["check_cer"] else None,
        "追いつき": (
            all(s["latency_sec"] <= LATENCY_LIMIT_SEC for s in segments)
            and result["max_queue"] <= QUEUE_LIMIT
        ) if result["check_latency"] else None,
        "順": result["order"] == sorted(result["order"]),
    }


def main() -> int:
    """場面を作って流し、結果を poc/results/ へ書く。"""
    out_dir = ROOT / "poc" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="voice-paste-poc-"))

    scenes, peak = build_scenes(work_dir)
    client = WhisperWorkerClient(
        settings=LocalWhisperSettings(),
        ready_timeout_sec=WORKER_READY_TIMEOUT_SEC,
        log_dir=work_dir,
        stop_timeout_sec=WORKER_STOP_TIMEOUT_SEC,
    )
    client.start()
    stop = threading.Event()
    start_api_load(stop)

    results = []
    for scene in scenes:
        result = run_scene(scene, client, work_dir, peak)
        result["judgement"] = judge(result)
        results.append(result)
        print(json.dumps({"scene": scene.name, "judgement": result["judgement"],
                          "segments": len(result["segments"]), "max_queue": result["max_queue"]},
                         ensure_ascii=False), flush=True)

    stop.set()
    client.stop()
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
