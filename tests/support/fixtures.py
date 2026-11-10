"""実機のテストの共通フィクスチャ（コールバック先の受信先と、OpenAI API の代わりのエンドポイントと、本物の常駐サービスの起動と、pytest のプロセスの中で配線した常駐アプリ）。conftest が import して使う。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.inprocess import InProcessApp, WavInput, start_inprocess_app
from voice_paste.shared.settings import Settings


@pytest.fixture
def receiver() -> Iterator[CallbackReceiver]:
    """コールバック先のテスト用の受信先を 127.0.0.1 に立てる。"""
    callback_receiver = CallbackReceiver()
    callback_receiver.start()
    yield callback_receiver
    callback_receiver.stop()


@pytest.fixture
def start_inprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., InProcessApp]]:
    """常駐アプリを pytest のプロセスの中で配線する関数を返す。配線したアプリは、テストの後に止める。"""
    started: list[InProcessApp] = []

    def _start(*, settings: Settings, wav_input: WavInput) -> InProcessApp:
        """録音の入力に wav_input を差して配線し、後片付けの対象に覚える。"""
        app = start_inprocess_app(tmp_path, monkeypatch, settings=settings, wav_input=wav_input)
        started.append(app)
        return app

    yield _start
    for app in started:
        app.close()
