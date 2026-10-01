r"""刷新前（voice_paste_legacy）の応答時間を測る計測のスクリプト。

マイクの入力と利用者の操作は使わず、貼り付けのキーは送らない。
測った生の値と中央値を表示し、JSON でログフォルダへ保存する。

Usage:
# リポジトリ直下で、Windows の venv の Python から実行する（[] は任意の引数）
venv\Scripts\python.exe -m scripts.measure_legacy_latency [--runs 20] [--load-runs 5]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from unittest import mock

import numpy as np
import pyperclip
import scipy.io.wavfile as wavfile
from dotenv import dotenv_values

from voice_paste_legacy import config
from voice_paste_legacy import main as legacy_main
from voice_paste_legacy import tray as tray_module
from voice_paste_legacy.audio import recorder as recorder_module
from voice_paste_legacy.audio import volume as volume_module
from voice_paste_legacy.audio.recorder import AudioRecorder
from voice_paste_legacy.constants import LOG_DIR
from voice_paste_legacy.input import keyboard_sender
from voice_paste_legacy.logger import setup_logger
from voice_paste_legacy.transcription.whisper_transcriber import WhisperTranscriber
from voice_paste_legacy.utils import apply_yogo_replacements, load_yogo

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "nfr" / "fixtures"

# CUDA の DLL を持つ nvidia-* パッケージ（venv の site-packages/nvidia/{名前}/bin）
CUDA_DLL_PACKAGES = ("cublas", "cudnn", "cuda_nvrtc")

MS_PER_SECOND = 1000
# 録音の先頭から切り出す長さ（秒）
CLIP_SECONDS = 10
# 録音のフレームを溜める 1 塊の長さ（sounddevice の既定の塊に近い値）
CHUNK_FRAMES = 1024
# 計測の前に捨てる回数（モデルを温めた状態で測るため）
WARMUP_RUNS = 1
# セッションの終了から次のホットキーを受け付けるまでの待ち（秒）
SESSION_SETTLE_SECONDS = 0.1
# 録音の開始・終了を待つ上限（秒）
SESSION_TIMEOUT_SECONDS = 10


class _StubStream:
    """マイクを開かない録音ストリームの代わり。"""

    def start(self) -> None:
        """何もしない。"""

    def stop(self) -> None:
        """何もしない。"""

    def close(self) -> None:
        """何もしない。"""


class _FakeKeyboard:
    """貼り付けのキーを実際には送らず、最初に押された時刻だけを控える。"""

    def __init__(self) -> None:
        self.pressed_at: float | None = None

    def press(self, _key: object) -> None:
        """最初の 1 回だけ押された時刻を控える。"""
        if self.pressed_at is None:
            self.pressed_at = time.perf_counter()

    def release(self, _key: object) -> None:
        """何もしない。"""


class _BlockingModal:
    """録音中の画面の代わり。show は解除されるまで戻らない。"""

    def __init__(self, release: threading.Event) -> None:
        self._release = release

    def show(self) -> None:
        """セッションが進行中の状態を保つ。"""
        self._release.wait()


class _SessionProbe:
    """ホットキーの計測で、常駐の処理から受け取る時刻・イベント・コールバックを持つ。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.finished = threading.Event()
        self.release = threading.Event()
        self.started_at = 0.0
        self.hotkey_callbacks: dict[str, Callable[[], None]] = {}
        self.request_quit: Callable[[], None] | None = None


def apply_settings(settings_file: Path) -> None:
    """固めた設定を config の変数へ入れる（型は config.py の既存の値に合わせる）。"""
    for key, value in dotenv_values(settings_file).items():
        current = getattr(config, key)
        # bool は int の派生なので先に判定する
        parsed = value.lower() == "true" if isinstance(current, bool) else type(current)(value)
        setattr(config, key, parsed)


def prepend_cuda_path() -> None:
    """ワーカーのサブプロセスが CUDA の DLL を見つけられるよう PATH の先頭に足す。"""
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    cuda_dirs = [str(site_packages / "nvidia" / name / "bin") for name in CUDA_DLL_PACKAGES]
    os.environ["PATH"] = os.pathsep.join([*cuda_dirs, os.environ["PATH"]])


def load_clip(recording: Path, seconds: int) -> np.ndarray:
    """録音の先頭から指定の秒数だけ切り出す（モノラル 16 bit の WAV を前提にする）。"""
    sample_rate, samples = wavfile.read(recording)
    frames = sample_rate * seconds
    if len(samples) < frames:
        raise ValueError(f"録音が {seconds} 秒に足りません: {recording}")
    return samples[:frames]


def make_recorder(clip: np.ndarray) -> AudioRecorder:
    """録音を止める直前の状態（フレームが溜まったストリーム）の AudioRecorder を作る。"""
    recorder = AudioRecorder()
    recorder._frames = [
        clip[start : start + CHUNK_FRAMES].reshape(-1, 1)
        for start in range(0, len(clip), CHUNK_FRAMES)
    ]
    recorder._stream = _StubStream()  # type: ignore[assignment]
    return recorder


def measure_model_load(runs: int) -> tuple[list[float], WhisperTranscriber]:
    """ワーカーの起動からモデルの読み込みが終わるまでをミリ秒で測る。最後のワーカーは生かして返す。"""
    values: list[float] = []
    transcriber: WhisperTranscriber | None = None
    for _ in range(runs):
        if transcriber is not None:
            transcriber._stop_worker()
        start = time.perf_counter()
        transcriber = WhisperTranscriber()
        values.append((time.perf_counter() - start) * MS_PER_SECOND)
    if transcriber is None:
        raise ValueError("読み込みの回数は 1 以上にしてください")
    return values, transcriber


def measure_paste_latency(
    transcriber: WhisperTranscriber, clip: np.ndarray, runs: int, wav_path: Path
) -> list[float]:
    """録音を止めてから貼り付けのキーを押す直前までをミリ秒で測る。先頭は捨てる回の値。"""
    keyboard = _FakeKeyboard()
    original_clipboard = pyperclip.paste()
    values: list[float] = []
    try:
        with mock.patch.object(keyboard_sender, "_keyboard", keyboard):
            for _ in range(runs + WARMUP_RUNS):
                recorder = make_recorder(clip)
                keyboard.pressed_at = None
                start = time.perf_counter()
                # 録音を止めて保存 → 用語集の読み込み → 文字起こし → 補正 → クリップボード → 貼り付けの待ち
                audio_file = recorder.stop_and_save(wav_path)
                glossary = load_yogo(config.YOGO_FILE)
                text = apply_yogo_replacements(transcriber.transcribe(audio_file), glossary)
                keyboard_sender.copy_to_clipboard(text)
                keyboard_sender.send_paste()
                if keyboard.pressed_at is None:
                    raise RuntimeError("貼り付けのキーが押されなかった")
                values.append((keyboard.pressed_at - start) * MS_PER_SECOND)
    finally:
        # 計測でクリップボードを書き換えたので、元の文字へ戻す
        pyperclip.copy(original_clipboard)
    return values


def measure_hotkey_response(runs: int) -> tuple[list[float], list[float]]:
    """ホットキーを受けてから録音が始まるまでと、処理中のホットキーを捨てるまでをミリ秒で測る。"""
    probe = _SessionProbe()
    original_run_once = legacy_main._run_once

    def fake_hotkeys(mapping: dict[str, Callable[[], None]]) -> mock.MagicMock:
        probe.hotkey_callbacks.update(mapping)
        return mock.MagicMock()

    def fake_build_tray(
        hotkey: str,
        on_start_session: Callable[[], None],
        on_settings: Callable[[], None],
        on_restart: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> mock.MagicMock:
        probe.request_quit = on_quit
        return mock.MagicMock()

    def fake_modal(**_kwargs: object) -> _BlockingModal:
        # 録音が始まった時点（recorder.start の後）の時刻を控える
        probe.started_at = time.perf_counter()
        probe.started.set()
        return _BlockingModal(probe.release)

    def run_once(*args: object, **kwargs: object) -> None:
        try:
            original_run_once(*args, **kwargs)
        finally:
            probe.finished.set()

    start_values: list[float] = []
    busy_values: list[float] = []
    # マイク・トレイ・ホットキーの監視・システム音量の変更は使わず、常駐のループとセッションの入口を実物で動かす
    with (
        mock.patch.object(legacy_main, "_create_transcriber", return_value=mock.MagicMock()),
        mock.patch.object(legacy_main, "_run_once", run_once),
        mock.patch.object(legacy_main.pynput_keyboard, "GlobalHotKeys", fake_hotkeys),
        mock.patch.object(legacy_main, "RecordingModal", fake_modal),
        mock.patch.object(tray_module, "build_tray_icon", fake_build_tray),
        mock.patch.object(recorder_module.sd, "InputStream", lambda **_: _StubStream()),
        mock.patch.object(volume_module, "fade_volume"),
    ):
        resident = threading.Thread(target=legacy_main._run_resident, daemon=True)
        resident.start()
        deadline = time.monotonic() + SESSION_TIMEOUT_SECONDS
        while config.RESIDENT_HOTKEY not in probe.hotkey_callbacks:
            if time.monotonic() > deadline:
                raise TimeoutError("常駐のホットキーが登録されなかった")
            time.sleep(SESSION_SETTLE_SECONDS)
        request_session = probe.hotkey_callbacks[config.RESIDENT_HOTKEY]

        for _ in range(runs):
            probe.started.clear()
            probe.finished.clear()
            probe.release.clear()
            # 待機中のホットキー: 受けてから録音が始まるまで
            begin = time.perf_counter()
            request_session()
            if not probe.started.wait(SESSION_TIMEOUT_SECONDS):
                raise TimeoutError("録音が始まらなかった")
            start_values.append((probe.started_at - begin) * MS_PER_SECOND)
            # セッション中のホットキー: 受けて捨てるまで
            begin = time.perf_counter()
            request_session()
            busy_values.append((time.perf_counter() - begin) * MS_PER_SECOND)
            # セッションを終えて、次の回の待機中へ戻す
            probe.release.set()
            probe.finished.wait(SESSION_TIMEOUT_SECONDS)
            time.sleep(SESSION_SETTLE_SECONDS)

        if probe.request_quit is None:
            raise RuntimeError("常駐の終了を要求できなかった")
        probe.request_quit()
        resident.join(timeout=SESSION_TIMEOUT_SECONDS)
    return start_values, busy_values


def summarize(values: list[float]) -> dict[str, object]:
    """生の値と中央値・最小・最大をまとめる。"""
    return {
        "median_ms": round(statistics.median(values), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
        "values_ms": [round(value, 2) for value in values],
    }


def parse_args() -> argparse.Namespace:
    """引数を読む。"""
    parser = argparse.ArgumentParser(description="刷新前の応答時間を測る")
    parser.add_argument("--runs", type=int, default=20, help="各計測の回数")
    parser.add_argument("--load-runs", type=int, default=5, help="モデルの読み込みを測る回数")
    parser.add_argument(
        "--recording",
        type=Path,
        default=FIXTURES_DIR / "recordings" / "20260930010513.wav",
        help="先頭 10 秒を使う録音",
    )
    parser.add_argument(
        "--settings", type=Path, default=FIXTURES_DIR / "whisper.env", help="固めた文字起こしの設定"
    )
    parser.add_argument(
        "--yogo", type=Path, default=FIXTURES_DIR / "yogo.csv", help="固めた用語集"
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, object]:
    """全ての計測を回して結果をまとめる。"""
    apply_settings(args.settings)
    config.YOGO_FILE = args.yogo
    prepend_cuda_path()
    setup_logger(config.LOG_LEVEL)
    clip = load_clip(args.recording, CLIP_SECONDS)

    print("ホットキーの受付を測っています...")
    start_values, busy_values = measure_hotkey_response(args.runs)
    print("モデルの読み込みを測っています...")
    load_values, transcriber = measure_model_load(args.load_runs)
    print("話し終えてから貼り付くまでを測っています...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        paste_values = measure_paste_latency(
            transcriber, clip, args.runs, Path(tmp_dir) / "recording.wav"
        )

    return {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "recording": args.recording.name,
        "clip_seconds": CLIP_SECONDS,
        "whisper_model": config.WHISPER_MODEL,
        "whisper_device": config.WHISPER_DEVICE,
        "hotkey_to_recording_start": summarize(start_values),
        "hotkey_dropped_while_busy": summarize(busy_values),
        "model_load": summarize(load_values),
        "paste_latency_warmup_ms": round(paste_values[0], 2),
        "paste_latency": summarize(paste_values[WARMUP_RUNS:]),
    }


def main() -> int:
    """計測を回し、結果を表示してログフォルダへ JSON で保存する。"""
    args = parse_args()
    try:
        result = run(args)
    except Exception:
        traceback.print_exc()
        return 1
    output = LOG_DIR / f"{datetime.now():%Y%m%d%H%M%S}_latency_measure.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"保存先: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
