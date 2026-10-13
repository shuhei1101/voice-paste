"""integrations/whisper/worker.py（run_worker）の単体テスト。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

AUDIO_PATH = "C:/recordings/recording.wav"


@pytest.fixture(autouse=True)
def isolated_faulthandler(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """ワーカーが入口で有効にする faulthandler を、テストのプロセスに効かせない。"""
    enable = MagicMock()
    monkeypatch.setattr("faulthandler.enable", enable)
    return enable


def _config_line(log_dir: Path) -> str:
    """config の 1 行（常駐 → ワーカー）を作る。"""
    return _message_line(
        "config",
        {
            "model": "large-v3",
            "device": "cuda",
            "compute_type": "float16",
            "cpu_threads": 0,
            "num_workers": 1,
            "log_dir": str(log_dir),
        },
    )


def _transcribe_line(*, vad_filter: bool = True, hotwords: str | None = None) -> str:
    """transcribe の 1 行（常駐 → ワーカー）を作る。hotwords が None ならキーごと載せない。"""
    payload: dict[str, Any] = {
        "audio_path": AUDIO_PATH,
        "language": "ja",
        "beam_size": 10,
        "best_of": 5,
        "temperature": 0.0,
        "vad_filter": vad_filter,
        "vad_threshold": 0.5,
        "vad_min_speech_ms": 250,
        "vad_min_silence_ms": 2000,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.6,
    }
    if hotwords is not None:
        payload["hotwords"] = hotwords
    return _message_line("transcribe", payload)


def _message_line(message_type: str, payload: dict[str, Any]) -> str:
    """種類と中身から標準入力の 1 行を作る。"""
    return json.dumps({"type": message_type, "payload": payload}, ensure_ascii=False) + "\n"


def _segment(text: str, end: float) -> SimpleNamespace:
    """faster-whisper の区間（文字と終わりの時刻）を作る。"""
    return SimpleNamespace(text=text, end=end)


def _model_returning(*results: list[SimpleNamespace] | Exception) -> MagicMock:
    """transcribe を呼ぶたびに results を順に返す（例外なら送出する）モデルを作る。"""
    info = SimpleNamespace(duration=2.0, language="ja", language_probability=0.99)
    model = MagicMock()
    model.transcribe.side_effect = [
        result if isinstance(result, Exception) else (iter(result), info) for result in results
    ]
    return model


def _run(stdin_lines: list[str], load_model: MagicMock) -> tuple[int, list[dict[str, Any]]]:
    """標準入力の行を渡して run_worker を動かし、終了コードと出力のメッセージを返す。"""
    from voice_paste.integrations.whisper.worker import run_worker

    stdout = io.StringIO()
    exit_code = run_worker(io.StringIO("".join(stdin_lines)), stdout, load_model)
    messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
    return exit_code, messages


# === run_worker ===


def test_run_worker(tmp_path: Path) -> None:
    """ready の後に進みと結果を返す（正常系）。"""
    # 準備
    model = _model_returning([_segment("今日は", 1.0), _segment("晴れ", 2.0)])
    load_model = MagicMock(return_value=model)

    # 実行
    exit_code, messages = _run([_config_line(tmp_path), _transcribe_line()], load_model)

    # 検証
    assert [message["type"] for message in messages] == ["ready", "progress", "progress", "result"]
    assert exit_code == 0


def test_run_worker_when_model_load_failed(tmp_path: Path) -> None:
    """モデルを読めなければ error で終わる（正常系）。"""
    # 準備
    load_model = MagicMock(side_effect=RuntimeError("モデルを読めない"))

    # 実行
    exit_code, messages = _run([_config_line(tmp_path), _transcribe_line()], load_model)

    # 検証
    assert [message["type"] for message in messages] == ["error"]
    assert exit_code == 1


def test_run_worker_when_transcribe_failed(tmp_path: Path) -> None:
    """1 件の失敗では終わらず次の行を処理する（正常系）。"""
    # 準備
    model = _model_returning(RuntimeError("起こせない"), [_segment("今日は", 1.0)])
    load_model = MagicMock(return_value=model)

    # 実行
    exit_code, messages = _run(
        [_config_line(tmp_path), _transcribe_line(), _transcribe_line()], load_model
    )

    # 検証
    assert [message["type"] for message in messages] == ["ready", "error", "progress", "result"]
    assert exit_code == 0


def test_run_worker_when_blank_segment(tmp_path: Path) -> None:
    """区間の空白を除き、空の区間を result に含めない（正常系）。"""
    # 準備
    model = _model_returning([_segment(" 今日は ", 1.0), _segment(" ", 2.0)])
    load_model = MagicMock(return_value=model)

    # 実行
    _, messages = _run([_config_line(tmp_path), _transcribe_line()], load_model)

    # 検証
    assert [message["type"] for message in messages].count("progress") == 2
    assert messages[-1]["type"] == "result"
    assert messages[-1]["payload"]["segments"] == ["今日は"]


def test_run_worker_when_vad_disabled(tmp_path: Path) -> None:
    """VAD がオフなら vad_parameters を渡さない（正常系）。"""
    # 準備
    model = _model_returning([_segment("今日は", 1.0)])
    load_model = MagicMock(return_value=model)

    # 実行
    _run([_config_line(tmp_path), _transcribe_line(vad_filter=False)], load_model)

    # 検証（vad_parameters は渡さないか None で渡すかのどちらでもよい）
    request = model.transcribe.call_args.kwargs
    assert request["vad_filter"] is False
    assert request.get("vad_parameters") is None


def test_run_worker_when_hotwords(tmp_path: Path) -> None:
    """手がかりを hotwords に渡す（正常系）。"""
    # 準備
    model = _model_returning([_segment("今日は", 1.0)])
    load_model = MagicMock(return_value=model)

    # 実行
    _run(
        [_config_line(tmp_path), _transcribe_line(hotwords="voice-paste、Whisper")], load_model
    )

    # 検証
    assert model.transcribe.call_args.kwargs["hotwords"] == "voice-paste、Whisper"


def test_run_worker_when_no_hotwords(tmp_path: Path) -> None:
    """手がかりが無ければ hotwords を None で渡す（正常系）。"""
    # 準備
    model = _model_returning([_segment("今日は", 1.0)])
    load_model = MagicMock(return_value=model)

    # 実行
    _run([_config_line(tmp_path), _transcribe_line()], load_model)

    # 検証
    assert model.transcribe.call_args.kwargs["hotwords"] is None
