"""単一ユースケース「録音を文字に起こす」の E2E テスト（文字起こしの手がかりを渡す正常シナリオ）。

常駐アプリを pytest のプロセスの中で `build_handlers` で配線し、ホットキーの入口（`start_local_session`）から録音を始める
（起動・トレイ・ホットキーの受付は通さない）。録音の入力は、Windows の音声合成（SAPI）で決めた文を書き出した WAV を流すものに
差し替え、マイクもスピーカーも通さない。システム音量・貼り付けのキー・通知は差し替える。
文字起こしはローカルの Whisper（GPU）で、クリップボードは実物を使う（テストの後に元の文字へ戻す）。
文字起こしワーカーは、faster-whisper へ渡された hotwords を記録する入口（`tests/support/hotwords_probe_worker.py`）から起動し、
常駐アプリがワーカーへ送った要求と、ワーカーが faster-whisper へ渡した値を確かめる。
実機の Windows と GPU が要る（`--run-e2e` が無ければ skip する）。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyperclip
import pytest

import voice_paste.integrations.whisper.client as client_module
from tests.support.hotwords_probe_worker import PROBE_FILE_ENV
from tests.support.inprocess import InProcessApp, make_settings, speech_input
from tests.support.real_service import REPO_ROOT, SOURCE_DIR
from voice_paste.integrations.whisper.client import WhisperWorkerClient
from voice_paste.shared.settings import HintPresetSettings

pytestmark = pytest.mark.real_machine

StartInProcess = Callable[..., InProcessApp]

PROBE_WORKER_MODULE = "tests.support.hotwords_probe_worker"
"""ワーカーの代わりに起動する、hotwords を記録する入口のモジュール。"""

PASTE_AND_SEND = "paste_and_send"
"""確定に選ぶ出力先の ID（貼り付けて送信）。"""

HINT_PRESETS = [
    HintPresetSettings(name="開発", words=["voice-paste", "Whisper"]),
    HintPresetSettings(name="秘密", words=["渡さない語"], enabled=False),
    HintPresetSettings(name="会議", words=["議事録", "返信"]),
]
"""手がかりのプリセット（語を 2 つずつ持つ有効なものが 2 つ、語を持つ無効のものが 1 つ。無効のものは有効の間に置く）。"""

EXPECTED_HINT = "voice-paste、Whisper、議事録、返信"
"""有効なプリセットの語を一覧の順に読点（、）でつないだ手がかり。"""


def _spy_transcribe_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """常駐アプリがワーカーへ送る transcribe の要求の中身を、送るたびに控える。"""
    requests: list[dict[str, Any]] = []
    original = WhisperWorkerClient._send

    def _send(self: WhisperWorkerClient, message_type: str, **payload: object) -> None:
        """transcribe なら中身を控えてから、本物で送る。"""
        if message_type == "transcribe":
            requests.append(dict(payload))
        original(self, message_type, **payload)

    monkeypatch.setattr(WhisperWorkerClient, "_send", _send)
    return requests


def test_normal_when_hint(
    start_inprocess: StartInProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clipboard_sentinel: str,
) -> None:
    """有効な手がかりのプリセットの語が、一覧の順に読点でつながってワーカーへ送られ、faster-whisper の hotwords に渡される（正常シナリオ（文字起こしの手がかりを渡す））。"""
    # 準備
    probe_file = tmp_path / "hotwords.jsonl"
    monkeypatch.setenv(PROBE_FILE_ENV, str(probe_file))
    # ワーカーが、この作業ツリーの src と、記録する入口（tests）を読めるようにする
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(SOURCE_DIR), str(REPO_ROOT)]))
    monkeypatch.setattr(client_module, "WORKER_MODULE", PROBE_WORKER_MODULE)
    requests = _spy_transcribe_requests(monkeypatch)
    settings = make_settings(only_paste_and_send=True).model_copy(update={"hint_presets": HINT_PRESETS})
    app = start_inprocess(settings=settings, wav_input=speech_input(tmp_path))

    # 実行
    app.start_hotkey()
    app.manager.complete(output_id=PASTE_AND_SEND)

    # 検証
    assert app.wait_idle()
    [request] = requests
    assert request["hotwords"] == EXPECTED_HINT
    assert "渡さない語" not in request["hotwords"]
    passed = [json.loads(line) for line in probe_file.read_text(encoding="utf-8").splitlines()]
    assert passed == [EXPECTED_HINT]
    [recording] = app.history_files(".wav")
    [text_file] = app.history_files(".txt")
    assert recording.stem == text_file.stem
    assert text_file.read_text(encoding="utf-8") == pyperclip.paste()
    assert len(app.keys.pasted) == 1
