"""話し終えてから貼り付くまでの時間（paste_latency）の非機能要件テスト。

固めた設定（tests/nfr/fixtures/whisper.env の large-v3・cuda）と用語集（tests/nfr/fixtures/yogo.csv）で
build_handlers を一時フォルダの置き場所で配線し、モデルの読み込みを待つ。マイクの入力は刷新前と同じ録音の先頭 10 秒を
1024 フレームずつ渡すもの、音量の操作は何もしないもの、貼り付けのキーは押した時刻だけを控えるものに差し替える。
ホットキーの入口でセッションを始め、録音が 10 秒分たまったら貼り付けのみ（paste_only）で確定する。
クリップボードは実物を書き換えるため、測る前の文字を控えて測った後に戻す。
`--run-e2e` が無い環境・固めた設定や録音が無い環境・GPU が無い環境では skip する。
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pyperclip
import pytest
from scipy.io import wavfile

from tests.integration.helpers import wait_until
from tests.support.whisper_fixtures import (
    PASTE_LATENCY_RECORDING,
    YOGO_FILE,
    load_local_whisper_settings,
    requires_real_whisper,
)

if TYPE_CHECKING:
    from voice_paste.main import Handlers

pytestmark = [
    pytest.mark.real_machine,
    requires_real_whisper,
    pytest.mark.skipif(
        not PASTE_LATENCY_RECORDING.exists() or not YOGO_FILE.exists(),
        reason="tests/nfr/fixtures/ の録音と用語集が要る",
    ),
]

RUNS = 20
"""測る回数（先に捨てる 1 回を除く）。"""

WARMUP_RUNS = 1
"""測る前に捨てる回数（モデルを温めた状態で測るため）。"""

LATENCY_LIMIT_SEC = 1.59
"""話し終えてから貼り付くまでの時間の決定値（秒）。"""

CLIP_SEC = 10
"""録音の先頭から切り出す長さ（秒）。"""

CHUNK_FRAMES = 1024
"""録音を渡す 1 塊のフレーム数（sounddevice の既定の塊に近い値）。"""

PASTE_TIMEOUT_SEC = 60.0
"""貼り付けのキーが押されるのを待つ上限。"""

SETTLE_TIMEOUT_SEC = 10.0
"""貼り付けのキーを押した後、セッションが終わって次の開始を受け付けるまで待つ上限。"""


class _FinishedStream:
    """マイクを開かない録音ストリームの代わり。"""

    def stop(self) -> None:
        """何もしない。"""

    def close(self) -> None:
        """何もしない。"""


def _load_clip() -> np.ndarray:
    """刷新前と同じ録音の先頭 CLIP_SEC 秒を、モノラル 16 bit の音として返す。"""
    sample_rate, samples = wavfile.read(PASTE_LATENCY_RECORDING)
    frames = sample_rate * CLIP_SEC
    assert samples.ndim == 1, "モノラルの録音が要る"
    assert len(samples) >= frames, f"録音が {CLIP_SEC} 秒に足りない"
    return np.asarray(samples[:frames], dtype=np.int16)


def _measure_once(handlers: Handlers, pressed_at: list[float], pasted: threading.Event) -> float:
    """セッションを始めて確定し、確定を呼んでから貼り付けのキーが押されるまでの秒数を返す。"""
    manager = handlers.session_manager
    pressed_at.clear()
    pasted.clear()
    # 開始: 差し替えた入力が 10 秒分の音を一度に渡す（録音が 10 秒分たまった状態になる）
    manager.start("hotkey")
    # 確定: ここから、録音の保存・用語集の読み込み・文字起こし・補正・クリップボード・貼り付けの待ちを通る
    started = time.perf_counter()
    manager.complete(output_id="paste_only")
    assert pasted.wait(PASTE_TIMEOUT_SEC), "貼り付けのキーが押されなかった"
    elapsed = pressed_at[0] - started
    # 次の開始を受け付けるまで待つ
    assert wait_until(lambda: manager.current() is None, SETTLE_TIMEOUT_SEC)
    return elapsed


def test_paste_latency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """録音を止めてから貼り付けのキーを押す直前までの中央値が決定値以下である（実機）。"""
    import voice_paste.main as main_module
    from voice_paste.main import SETTINGS_MODEL
    from voice_paste.shared.constants import resolve_app_paths
    from voice_paste.shared.os_kind import CURRENT_OS
    from voice_paste.shared.settings import TranscriptionSettings

    # 準備: 差し替えるもの（マイクの入力・音量・貼り付けのキー）
    clip = _load_clip()
    pressed_at: list[float] = []
    pasted = threading.Event()

    def _open_input(on_frames: Any) -> _FinishedStream:
        """録音の先頭 10 秒を 1024 フレームずつ渡して、開いたストリームの代わりを返す。"""
        for start in range(0, len(clip), CHUNK_FRAMES):
            on_frames(clip[start : start + CHUNK_FRAMES].reshape(-1, 1))
        return _FinishedStream()

    def _send_paste(_key: str) -> None:
        """貼り付けのキーを送信せず、最初に押された時刻だけを控える。"""
        if not pressed_at:
            pressed_at.append(time.perf_counter())
        pasted.set()

    monkeypatch.setattr(main_module, "open_input", _open_input)
    monkeypatch.setattr(main_module, "send_paste", _send_paste)

    # 準備: 固めた設定と用語集で配線し、モデルの読み込みを待つ（クリップボードは測った後に戻す）
    settings = SETTINGS_MODEL(
        transcription=TranscriptionSettings(local_whisper=load_local_whisper_settings()),
        glossary_path=YOGO_FILE,
    )
    paths = resolve_app_paths(tmp_path)
    # OS ごとの実装は本物を選び、システム音量だけ何もしないものに差し替えて渡す
    adapters = replace(
        main_module.select_platform_adapters(CURRENT_OS, lock_file=paths.lock_file),
        lower_volume=lambda _ratio, _sec: 1.0,
        restore_volume=lambda _volume, _sec: None,
    )
    handlers = main_module.build_handlers(
        settings,
        paths,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: None,
        lambda *_args, **_kwargs: None,
        adapters=adapters,
    )
    original_clipboard = pyperclip.paste()
    elapsed_list: list[float] = []

    # 実行: 先に捨てる 1 回の後、RUNS 回測る
    try:
        for index in range(WARMUP_RUNS + RUNS):
            elapsed = _measure_once(handlers, pressed_at, pasted)
            if index >= WARMUP_RUNS:
                elapsed_list.append(elapsed)
    finally:
        pyperclip.copy(original_clipboard)
        handlers.session_manager.close()
        handlers.stop_engine()

    # 検証
    print(  # noqa: T201 測った値を実行の出力に残す
        f"paste_latency: n={len(elapsed_list)} raw={[round(v, 3) for v in elapsed_list]} "
        f"median={statistics.median(elapsed_list):.3f} min={min(elapsed_list):.3f} "
        f"max={max(elapsed_list):.3f} sec"
    )
    assert len(elapsed_list) == RUNS
    assert statistics.median(elapsed_list) <= LATENCY_LIMIT_SEC
