"""実機のテストの共通フィクスチャ（返送先の受け口と、本物の常駐サービスの起動）。conftest が import して使う。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import CallbackReceiver
from tests.support.real_service import RealService


@pytest.fixture
def receiver() -> Iterator[CallbackReceiver]:
    """返送先のテスト用の受け口を 127.0.0.1 に立てる。"""
    callback_receiver = CallbackReceiver()
    callback_receiver.start()
    yield callback_receiver
    callback_receiver.stop()


@pytest.fixture
def start_service(tmp_path: Path) -> Iterator[Callable[..., RealService]]:
    """本物の常駐サービスを起動する関数を返す。起動したサービスは、テストの後に終わらせる。"""
    started: list[RealService] = []

    def _start(
        extra_settings: str = "",
        *,
        accept_injected_hotkeys: bool = False,
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
            accept_injected_hotkeys=accept_injected_hotkeys,
            port=port,
            wait_for_api=wait_for_api,
        )
        started.append(service)
        return service

    yield _start
    for service in started:
        service.shutdown()
