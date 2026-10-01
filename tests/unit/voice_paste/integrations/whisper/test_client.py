"""integrations/whisper/client.py（WhisperWorkerClient の start・transcribe・stop）の単体テスト。

子プロセス（subprocess.Popen）は、標準入出力の JSON Lines で応答する偽物に差し替える。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from voice_paste.shared.settings import LocalWhisperSettings

READY_TIMEOUT_SEC = 0.1
STOP_TIMEOUT_SEC = 0.1
SLOW_READY_DELAY_SEC = 0.3
AUDIO_PATH = Path("recording.wav")
END_OF_STREAM = None

# 子プロセスが、受け取った 1 件のメッセージに応じて何を返すか
Script = Callable[["FakeProcess", dict[str, Any]], None]


class FakePipe:
    """子プロセスの標準出力・標準エラー。EOF が来るまで readline が待つ。"""

    def __init__(self) -> None:
        self._lines: queue.Queue[str | None] = queue.Queue()

    def push(self, line: str | None) -> None:
        """1 行（None なら EOF）を読めるようにする。"""
        self._lines.put(line)

    def readline(self) -> str:
        """次の 1 行を返す。EOF なら空文字を返し続ける。"""
        line = self._lines.get()
        if line is END_OF_STREAM:
            self._lines.put(END_OF_STREAM)
            return ""
        return line

    def __iter__(self) -> FakePipe:
        """行の反復（EOF で終わる）。"""
        return self

    def __next__(self) -> str:
        """次の 1 行。EOF なら反復を終える。"""
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class FakeStdin:
    """子プロセスの標準入力。書かれた行を JSON として読み、台本へ渡す。"""

    def __init__(self, process: FakeProcess) -> None:
        self._process = process
        self._buffer = ""
        self.closed = False

    def write(self, text: str) -> int:
        """書かれた文字のうち、改行で終わった行を 1 件ずつ子プロセスへ渡す。"""
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._process.receive(json.loads(line))
        return len(text)

    def flush(self) -> None:
        """何もしない。"""

    def close(self) -> None:
        """閉じる。標準入力が閉じたら終わる子プロセスなら、ここで終わる。"""
        self.closed = True
        if not self._process.hangs_on_close:
            self._process.finish(0)


class FakeProcess:
    """subprocess.Popen の偽物。台本のとおりに応答し、止められたら EOF を返して終わる。"""

    pid = 4321

    def __init__(
        self, script: Script, *, hangs_on_close: bool = False, terminate_ends: bool = True
    ) -> None:
        self._script = script
        self.hangs_on_close = hangs_on_close
        self._terminate_ends = terminate_ends
        self.stdin = FakeStdin(self)
        self.stdout = FakePipe()
        self.stderr = FakePipe()
        self.returncode: int | None = None
        self.received: list[dict[str, Any]] = []
        self.signals: list[str] = []
        self.wait_timeouts: list[float | None] = []

    def receive(self, message: dict[str, Any]) -> None:
        """標準入力へ届いたメッセージを記録し、台本へ渡す。"""
        self.received.append(message)
        self._script(self, message)

    def reply(self, message_type: str, **payload: Any) -> None:
        """標準出力へメッセージを 1 行書く。"""
        line = json.dumps({"type": message_type, "payload": payload}, ensure_ascii=False)
        self.stdout.push(line + "\n")

    def finish(self, returncode: int) -> None:
        """子プロセスが終わった状態にする（標準出力・標準エラーは EOF になる）。"""
        if self.returncode is None:
            self.returncode = returncode
            self.stdout.push(END_OF_STREAM)
            self.stderr.push(END_OF_STREAM)

    def poll(self) -> int | None:
        """終わっていれば終了コード、動いていれば None を返す。"""
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        """終わるのを待つ。動いたままなら TimeoutExpired を送出する。"""
        self.wait_timeouts.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout or 0.0)
        return self.returncode

    def terminate(self) -> None:
        """終了を求める。terminate_ends が False なら無視して動き続ける。"""
        self.signals.append("terminate")
        if self._terminate_ends:
            self.finish(-15)

    def kill(self) -> None:
        """強制的に終わらせる。"""
        self.signals.append("kill")
        self.finish(-9)

    @property
    def was_stopped(self) -> bool:
        """terminate か kill が呼ばれたか。"""
        return bool(self.signals)


class FakePopen:
    """subprocess.Popen の差し替え。呼ばれるたびに、用意した子プロセスを順に返す。"""

    def __init__(self, *processes: FakeProcess) -> None:
        self._processes = list(processes)
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeProcess:
        """起動の引数を記録し、次の子プロセスを返す（用意した数を超えて起動したらテストを落とす）。"""
        self.calls.append((args, kwargs))
        if len(self.calls) > len(self._processes):
            raise AssertionError("用意した数を超えて子プロセスを起動した")
        return self._processes[len(self.calls) - 1]


# === 子プロセスの台本 ===


def ready_worker(process: FakeProcess, message: dict[str, Any]) -> None:
    """config に ready、transcribe に進みと結果を返す、正常なワーカー。"""
    if message["type"] == "config":
        process.reply("ready")
    elif message["type"] == "transcribe":
        process.reply("progress", end=1.0, duration=2.0)
        process.reply("result", segments=["今日は", "晴れ"])


def crash_on_transcribe_worker(process: FakeProcess, message: dict[str, Any]) -> None:
    """ready は返すが、transcribe の応答の途中で終わる（落ちる）ワーカー。"""
    if message["type"] == "config":
        process.reply("ready")
    elif message["type"] == "transcribe":
        process.reply("progress", end=0.5, duration=2.0)
        process.finish(1)


def error_on_transcribe_worker(process: FakeProcess, message: dict[str, Any]) -> None:
    """ready は返すが、transcribe に error を返して動き続けるワーカー。"""
    if message["type"] == "config":
        process.reply("ready")
    elif message["type"] == "transcribe":
        process.reply("error", message="起こせない")


def model_load_failed_worker(process: FakeProcess, message: dict[str, Any]) -> None:
    """config に ready ではなく error を返して終わるワーカー。"""
    if message["type"] == "config":
        process.reply("error", message="モデルを読めない")
        process.finish(1)


def silent_worker(process: FakeProcess, message: dict[str, Any]) -> None:
    """何も返さないワーカー。"""


def slow_ready_worker(process: FakeProcess, message: dict[str, Any]) -> None:
    """config から少し遅れて ready を返すワーカー。"""
    if message["type"] == "config":
        threading.Timer(SLOW_READY_DELAY_SEC, process.reply, args=["ready"]).start()


# === 共通の準備 ===


@pytest.fixture
def local_whisper_settings() -> LocalWhisperSettings:
    """既定と違う値の、ローカルの Whisper の設定を返す。"""
    return LocalWhisperSettings(
        language="en",
        beam_size=3,
        best_of=2,
        temperature=0.2,
        vad_filter=False,
        vad_threshold=0.4,
        vad_min_speech_ms=300,
        vad_min_silence_ms=1500,
        condition_on_previous_text=True,
        no_speech_threshold=0.7,
    )


@pytest.fixture
def make_client(
    tmp_path: Path, local_whisper_settings: LocalWhisperSettings
) -> Callable[..., Any]:
    """WhisperWorkerClient を作る関数を返す（立て直しの上限・終わりを待つ時間は短くする）。"""

    def _make_client(**overrides: Any) -> Any:
        """既定の引数に overrides を重ねて WhisperWorkerClient を作る。"""
        from voice_paste.integrations.whisper.client import WhisperWorkerClient

        arguments: dict[str, Any] = {
            "settings": local_whisper_settings,
            "ready_timeout_sec": READY_TIMEOUT_SEC,
            "log_dir": tmp_path / "log",
            "stop_timeout_sec": STOP_TIMEOUT_SEC,
        }
        return WhisperWorkerClient(**{**arguments, **overrides})

    return _make_client


@pytest.fixture
def install_popen(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakePopen]:
    """subprocess.Popen を、渡した子プロセスを順に返す偽物に差し替える関数を返す。"""

    def _install(*processes: FakeProcess) -> FakePopen:
        """差し替えて、起動の記録を持つ偽物を返す。"""
        fake_popen = FakePopen(*processes)
        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        return fake_popen

    return _install


# === start ===


def test_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_client: Callable[..., Any],
    install_popen: Callable[..., FakePopen],
) -> None:
    """config を送り ready を受けて立ち上がる（正常系）。"""
    # 準備（venv に cublas・cudnn の bin だけがある）
    cublas_bin = tmp_path / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
    cudnn_bin = tmp_path / "Lib" / "site-packages" / "nvidia" / "cudnn" / "bin"
    nvrtc_bin = tmp_path / "Lib" / "site-packages" / "nvidia" / "cuda_nvrtc" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setenv("PATH", "C:/base")
    process = FakeProcess(ready_worker)
    fake_popen = install_popen(process)
    client = make_client()

    # 実行
    client.start()

    # 検証
    assert process.received[0]["type"] == "config"
    path_entries = fake_popen.calls[0][1]["env"]["PATH"].split(os.pathsep)
    assert set(path_entries[:2]) == {str(cublas_bin), str(cudnn_bin)}
    assert str(nvrtc_bin) not in path_entries


def test_start_when_model_load_failed(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """ready の代わりに error が届いたら EngineError にする（異常系）。"""
    from voice_paste.shared.errors import EngineError

    # 準備
    install_popen(FakeProcess(model_load_failed_worker))
    client = make_client()

    # 実行・検証
    with pytest.raises(EngineError, match="モデルを読めない"):
        client.start()


def test_start_when_ready_timeout(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """立て直しで ready を待ちきれなければ子プロセスを止めて EngineError にする（異常系）。"""
    from voice_paste.shared.errors import EngineError

    # 準備
    process = FakeProcess(silent_worker)
    install_popen(process)
    client = make_client()

    # 実行・検証
    with pytest.raises(EngineError):
        client.start(ready_timeout_sec=READY_TIMEOUT_SEC)
    assert process.was_stopped


def test_start_when_first_ready_is_slow(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """起動時の 1 回目は上限をかけずに ready を待つ（正常系）。"""
    # 準備（ready は _ready_timeout_sec より遅れて届く）
    process = FakeProcess(slow_ready_worker)
    install_popen(process)
    client = make_client(ready_timeout_sec=READY_TIMEOUT_SEC)

    # 実行
    client.start()

    # 検証
    assert not process.was_stopped


# === transcribe ===


def test_transcribe_when_worker_crashed_once(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """1 回落ちてもやり直しで結果を得る（正常系）。"""
    # 準備
    fake_popen = install_popen(FakeProcess(crash_on_transcribe_worker), FakeProcess(ready_worker))
    client = make_client()
    client.start()

    # 実行
    segments = client.transcribe(AUDIO_PATH)

    # 検証
    assert segments == ["今日は", "晴れ"]
    assert len(fake_popen.calls) == 2


def test_transcribe_when_retry_crashed(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """やり直しも落ちたら EngineError にし、次に備えて起動し直す（異常系）。"""
    from voice_paste.shared.errors import EngineError

    # 準備（3 つ目は次の録音に備えて起動し直したワーカー）
    fake_popen = install_popen(
        FakeProcess(crash_on_transcribe_worker),
        FakeProcess(crash_on_transcribe_worker),
        FakeProcess(ready_worker),
    )
    client = make_client()
    client.start()

    # 実行・検証
    with pytest.raises(EngineError):
        client.transcribe(AUDIO_PATH)
    assert len(fake_popen.calls) == 3


def test_transcribe(
    local_whisper_settings: LocalWhisperSettings,
    make_client: Callable[..., Any],
    install_popen: Callable[..., FakePopen],
) -> None:
    """進みを知らせ、区間ごとの文字を返す（正常系）。"""
    # 準備
    process = FakeProcess(ready_worker)
    install_popen(process)
    client = make_client()
    client.start()
    progress_calls: list[tuple[float, float]] = []

    # 実行
    segments = client.transcribe(
        AUDIO_PATH, on_progress=lambda end, duration: progress_calls.append((end, duration))
    )

    # 検証
    assert segments == ["今日は", "晴れ"]
    assert progress_calls == [(1.0, 2.0)]
    assert process.received[-1] == {
        "type": "transcribe",
        "payload": {
            "audio_path": str(AUDIO_PATH),
            "language": "en",
            "beam_size": 3,
            "best_of": 2,
            "temperature": 0.2,
            "vad_filter": False,
            "vad_threshold": 0.4,
            "vad_min_speech_ms": 300,
            "vad_min_silence_ms": 1500,
            "condition_on_previous_text": True,
            "no_speech_threshold": 0.7,
        },
    }


def test_transcribe_when_worker_error(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """ワーカーが error を返したら起動し直さずに EngineError にする（異常系）。"""
    from voice_paste.shared.errors import EngineError

    # 準備
    fake_popen = install_popen(FakeProcess(error_on_transcribe_worker))
    client = make_client()
    client.start()

    # 実行・検証
    with pytest.raises(EngineError, match="起こせない"):
        client.transcribe(AUDIO_PATH)
    assert len(fake_popen.calls) == 1


# === stop ===


def test_stop_when_worker_hangs(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """標準入力を閉じても終わらなければ止める（正常系）。"""
    # 準備
    process = FakeProcess(ready_worker, hangs_on_close=True)
    install_popen(process)
    client = make_client()
    client.start()

    # 実行
    client.stop()

    # 検証
    assert process.stdin.closed
    assert "terminate" in process.signals


def test_stop_when_terminate_hangs(
    make_client: Callable[..., Any], install_popen: Callable[..., FakePopen]
) -> None:
    """terminate しても終わらなければ kill する（正常系）。"""
    # 準備
    process = FakeProcess(ready_worker, hangs_on_close=True, terminate_ends=False)
    install_popen(process)
    client = make_client(stop_timeout_sec=0.1)
    client.start()

    # 実行
    client.stop()

    # 検証
    assert process.signals == ["terminate", "kill"]
    assert process.wait_timeouts[:2] == [0.1, 0.1]
