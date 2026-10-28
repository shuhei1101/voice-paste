"""integrations/vad/adapter.py（load_vad_session・StreamingVad）の単体テスト。

onnxruntime の InferenceSession は偽物に差し替える。
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import onnxruntime
import pytest

from voice_paste.shared.errors import StartupError

WINDOW = 512
CONTEXT = 64
STATE_SHAPE = (1, 1, 128)
MODEL_FILE_NAME = "silero_vad_v6.onnx"


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
    monkeypatch: pytest.MonkeyPatch, without_faster_whisper: None
) -> None:
    """同梱のモデルを CPU で開き、faster_whisper を import しない（正常系）。"""
    import voice_paste.integrations.vad as vad_package
    from voice_paste.integrations.vad.adapter import load_vad_session

    # 準備: InferenceSession を、開かれたときのパスと、そのパスのファイルがあるかを控える偽物にする
    opened: dict[str, Any] = {}
    session = MagicMock()

    def _open(model_path: str, **kwargs: Any) -> MagicMock:
        opened["path"] = Path(model_path).resolve()
        opened["is_file"] = Path(model_path).is_file()
        opened["kwargs"] = kwargs
        return session

    monkeypatch.setattr(onnxruntime, "InferenceSession", _open)

    # 実行
    result = load_vad_session()

    # 検証: 常駐アプリのパッケージに同梱したモデルのファイルを CPU で開いて返し、faster_whisper を import していない
    bundled_model = (Path(vad_package.__file__).parent / "assets" / MODEL_FILE_NAME).resolve()
    assert opened["path"] == bundled_model
    assert opened["is_file"] is True
    assert opened["kwargs"]["providers"] == ["CPUExecutionProvider"]
    assert result is session
    assert "faster_whisper" not in sys.modules


def test_load_vad_session_when_model_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """モデルのファイルが無ければ起動の失敗にする（異常系）。"""
    import voice_paste.integrations.vad.adapter as adapter

    # 準備: モデルの置き場所を無いファイル名に差し替える（開く側は成功する偽物にして、ファイルの有無を確かめさせる）
    monkeypatch.setattr(adapter, "VAD_MODEL_RESOURCE", "assets/no_such_model.onnx")
    monkeypatch.setattr(onnxruntime, "InferenceSession", MagicMock())

    # 実行・検証
    with pytest.raises(StartupError, match="VAD"):
        adapter.load_vad_session()


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
