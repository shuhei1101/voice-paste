"""integrations/vad/adapter.py（load_vad_session・StreamingVad）の単体テスト。

onnxruntime の InferenceSession は偽物に、faster-whisper のパッケージの場所は一時フォルダに差し替える。
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import onnxruntime
import pytest

from voice_paste.shared.errors import StartupError

WINDOW = 512
CONTEXT = 64
STATE_SHAPE = (1, 1, 128)
MODEL_RELATIVE_PATH = Path("assets") / "silero_vad_v6.onnx"


def _make_session(probability: float = 0.9) -> MagicMock:
    """run が確率と、呼ぶたびに値の違う h・c を返す InferenceSession の偽物を作る。"""
    session = MagicMock()
    counter = itertools.count(1)

    def _run(_output_names: object, _input_feed: object) -> list[np.ndarray]:
        number = next(counter)
        return [
            np.array([probability], dtype=np.float32),
            np.full(STATE_SHAPE, number, dtype=np.float32),
            np.full(STATE_SHAPE, number + 100, dtype=np.float32),
        ]

    session.run.side_effect = _run
    return session


def _patch_find_spec(monkeypatch: pytest.MonkeyPatch, package_dir: Path | None) -> None:
    """faster_whisper の find_spec だけを、package_dir にあるパッケージ（無ければ見つからない）に差し替える。"""
    real_find_spec = importlib.util.find_spec

    def _find_spec(name: str, package: str | None = None) -> object:
        if name != "faster_whisper":
            return real_find_spec(name, package)
        if package_dir is None:
            return None
        return SimpleNamespace(submodule_search_locations=[str(package_dir)])

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)


def _package_dir(tmp_path: Path, package_found: bool) -> Path | None:
    """パッケージが見つかる場合は一時フォルダ（モデルのファイルは置かない）、見つからない場合は None を返す。"""
    return tmp_path if package_found else None


@pytest.fixture
def without_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    """faster_whisper とその下のモジュールを sys.modules から外す（読み込みが import し直せば戻って見つかる）。"""
    loaded = [
        module_name
        for module_name in sys.modules
        if module_name == "faster_whisper" or module_name.startswith("faster_whisper.")
    ]
    for module_name in loaded:
        monkeypatch.delitem(sys.modules, module_name)


# === load_vad_session ===


def test_load_vad_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, without_faster_whisper: None
) -> None:
    """同梱のモデルを CPU で開き、faster_whisper を import しない（正常系）。"""
    from voice_paste.integrations.vad.adapter import load_vad_session

    # 準備: パッケージの場所にモデルのファイルを置き、InferenceSession を偽物にする
    model_path = tmp_path / MODEL_RELATIVE_PATH
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"onnx")
    _patch_find_spec(monkeypatch, tmp_path)
    fake_inference_session = MagicMock()
    monkeypatch.setattr(onnxruntime, "InferenceSession", fake_inference_session)

    # 実行
    session = load_vad_session()

    # 検証
    fake_inference_session.assert_called_once()
    call = fake_inference_session.call_args
    assert Path(call.args[0]) == model_path
    assert call.kwargs["providers"] == ["CPUExecutionProvider"]
    assert session is fake_inference_session.return_value
    assert "faster_whisper" not in sys.modules


@pytest.mark.parametrize(
    "package_found",
    [
        pytest.param(False, id="package_not_found"),
        pytest.param(True, id="model_file_missing"),
    ],
)
def test_load_vad_session_when_model_missing(
    package_found: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """モデルのファイルが無ければ起動の失敗にする（異常系）。"""
    from voice_paste.integrations.vad.adapter import load_vad_session

    # 準備: パッケージが見つからないか、見つかってもモデルのファイルが無い（開く側は成功する偽物にして、ファイルの有無を確かめさせる）
    _patch_find_spec(monkeypatch, _package_dir(tmp_path, package_found))
    monkeypatch.setattr(onnxruntime, "InferenceSession", MagicMock())

    # 実行・検証
    with pytest.raises(StartupError, match="VAD"):
        load_vad_session()


# === StreamingVad ===


def test_streaming_vad_carries_state() -> None:
    """状態を次の窓へ持ち越す（正常系）。"""
    from voice_paste.integrations.vad.adapter import StreamingVad

    # 準備: 確率 0.9 と、呼ぶたびに違う h・c を返すセッションに、2 窓を続けて渡す
    session = _make_session(0.9)
    vad = StreamingVad(session)
    first_window = np.linspace(-0.5, 0.5, WINDOW, dtype=np.float32)
    second_window = np.full(WINDOW, 0.25, dtype=np.float32)

    # 実行
    vad(first_window)
    probability = vad(second_window)

    # 検証: 2 回目の run に、1 回目が返した h・c と、1 窓目の末尾 64 サンプルで始まる (1, 576) の入力が渡る
    assert probability == pytest.approx(0.9)
    second_feed = session.run.call_args_list[1].args[1]
    np.testing.assert_array_equal(second_feed["h"], np.full(STATE_SHAPE, 1, dtype=np.float32))
    np.testing.assert_array_equal(second_feed["c"], np.full(STATE_SHAPE, 101, dtype=np.float32))
    assert second_feed["input"].shape == (1, CONTEXT + WINDOW)
    assert second_feed["input"].dtype == np.float32
    np.testing.assert_array_equal(second_feed["input"][0, :CONTEXT], first_window[-CONTEXT:])
    np.testing.assert_array_equal(second_feed["input"][0, CONTEXT:], second_window)


def test_streaming_vad_starts_fresh() -> None:
    """新しく作ると状態を持ち越さない（正常系）。"""
    from voice_paste.integrations.vad.adapter import StreamingVad

    # 準備: 同じセッションで 2 つ作り、それぞれに 1 窓を渡す
    session = _make_session()
    window = np.full(WINDOW, 0.25, dtype=np.float32)
    zero_state = np.zeros(STATE_SHAPE, dtype=np.float32)
    zero_context = np.zeros(CONTEXT, dtype=np.float32)

    # 実行
    StreamingVad(session)(window)
    StreamingVad(session)(window)

    # 検証: どちらの run にも 0 の h・c と、0 の文脈が渡る
    first_feed = session.run.call_args_list[0].args[1]
    second_feed = session.run.call_args_list[1].args[1]
    np.testing.assert_array_equal(first_feed["h"], zero_state)
    np.testing.assert_array_equal(first_feed["c"], zero_state)
    np.testing.assert_array_equal(first_feed["input"][0, :CONTEXT], zero_context)
    np.testing.assert_array_equal(second_feed["h"], zero_state)
    np.testing.assert_array_equal(second_feed["c"], zero_state)
    np.testing.assert_array_equal(second_feed["input"][0, :CONTEXT], zero_context)
