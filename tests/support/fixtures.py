"""実機のテストの共通フィクスチャ（返送先の受け口と、本物の常駐サービスの起動と、pytest のプロセスの中で配線した常駐アプリ）。conftest が import して使う。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.inprocess import InProcessApp, WavInput, start_inprocess_app
from tests.support.real_service import RealService
from tests.support.resident_app import kill_service_processes_for
from voice_paste.shared.settings import Settings


@pytest.fixture
def receiver() -> Iterator[CallbackReceiver]:
    """返送先のテスト用の受け口を 127.0.0.1 に立てる。"""
    callback_receiver = CallbackReceiver()
    callback_receiver.start()
    yield callback_receiver
    callback_receiver.stop()


@pytest.fixture
def start_service(tmp_path: Path) -> Iterator[Callable[..., RealService]]:
    """本物の常駐サービスを起動する関数を返す。起動したサービスは、テストの後に終わらせる（同じ置き場所で後から起動したプロセスも止める）。"""
    started: list[RealService] = []

    def _start(
        extra_settings: str = "",
        *,
        port: int | None = None,
        wait_for_api: bool = True,
        prepare: Callable[[Path], None] | None = None,
    ) -> RealService:
        """設定を足して起動する。prepare は起動の前に、置き場所（空の一時フォルダ）へファイルを用意する関数。"""
        data_dir = tmp_path / f"data{len(started)}"
        data_dir.mkdir(parents=True, exist_ok=True)
        if prepare is not None:
            prepare(data_dir)
        service = RealService.launch(
            data_dir,
            extra_settings=extra_settings,
            port=port,
            wait_for_api=wait_for_api,
        )
        started.append(service)
        return service

    yield _start
    for service in started:
        service.shutdown()
        kill_service_processes_for(service.data_dir)


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
