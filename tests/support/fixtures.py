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

    def _start(extra_settings: str = "", *, accept_injected_hotkeys: bool = False) -> RealService:
        service = RealService.launch(
            tmp_path / f"data{len(started)}",
            extra_settings=extra_settings,
            accept_injected_hotkeys=accept_injected_hotkeys,
        )
        started.append(service)
        return service

    yield _start
    for service in started:
        service.shutdown()
