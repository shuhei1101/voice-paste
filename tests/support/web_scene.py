"""外の端末のブラウザの E2E の場面（常駐アプリ・API・Edge・開いた画面）を組み立てる補助。

常駐アプリは pytest のプロセスの中で `build_handlers` で配線する（文字起こしは本物の Whisper か、決めた文を返す関数）。
画面は Edge で `http://localhost:{ポート}/web/` を開く（localhost の Origin を許す Origin に入れる）。
偽のマイクには、SAPI で `SPEECH_TEXT` を書き出した WAV を流す。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.support.browser import BrowserPage, EdgeBrowser, open_page
from tests.support.inprocess import (
    SPEECH_TEXT,
    InProcessApi,
    InProcessApp,
    StubTranscription,
    WavInput,
    make_settings,
    silence_input,
    stub_transcription,
    synthesize_speech,
)
from voice_paste.shared.settings import Settings

StartInProcess = Callable[..., InProcessApp]
OpenEdge = Callable[..., EdgeBrowser]

SPEECH_WAV_NAME = "speech.wav"
"""偽のマイクに流す WAV のファイル名。"""

STUB_TEXT = "決めた文です"
"""文字起こしを差し替えたときに返す文。"""


@dataclass
class WebScene:
    """組み立てた場面。"""

    app: InProcessApp
    api: InProcessApi
    edge: EdgeBrowser
    page: BrowserPage
    stub: StubTranscription | None
    speech_wav: Path


def build_scene(
    start_inprocess: StartInProcess,
    open_edge: OpenEdge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stub_text: str | None = None,
    settings: Settings | None = None,
    allowed: bool = True,
    open_page_now: bool = True,
    wav_input: WavInput | None = None,
) -> WebScene:
    """常駐アプリを配線して API を待ち受けさせ、Edge で画面を開く。

    stub_text があれば、文字起こしをその文を返す関数に差し替える（無ければ本物の Whisper）。
    open_page_now が偽なら、画面は開かない（開く前に端末の保存を用意するケース）。
    wav_input は、ホットキーの録音に流す入力（渡さなければ無音）。
    """
    stub = stub_transcription(monkeypatch, stub_text) if stub_text is not None else None
    speech_wav = synthesize_speech(SPEECH_TEXT, tmp_path / SPEECH_WAV_NAME)
    app = start_inprocess(
        settings=settings or make_settings(only_paste_and_send=True),
        wav_input=wav_input or silence_input(tmp_path),
    )
    api = app.start_web_api(allowed=allowed)
    edge = open_edge(fake_microphone_wav=speech_wav)
    page = open_page(edge, api.web_origin) if open_page_now else edge.page
    return WebScene(app=app, api=api, edge=edge, page=page, stub=stub, speech_wav=speech_wav)


def record_for(page: BrowserPage, seconds: float) -> None:
    """録音開始を押し、録音の表示が出てから seconds 秒録って、録音停止・送信を押す。"""
    page.click("record_button")
    if not page.wait_until("!document.getElementById('recorder').hidden"):
        raise AssertionError("録音の表示が出なかった")
    time.sleep(seconds)
    page.click("stop_button")
