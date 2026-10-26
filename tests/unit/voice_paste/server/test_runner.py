"""server/runner.py（ApiServerRunner の start・stop）の単体テスト。

127.0.0.1 の空きポートで本物の uvicorn を立てる（GET だけを返す小さな app）。
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Iterator
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI

if TYPE_CHECKING:
    from voice_paste.server.runner import ApiServerRunner

START_TIMEOUT_SEC = 5.0
REQUEST_TIMEOUT_SEC = 5.0
LOOPBACK = "127.0.0.1"


def _free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ返す。"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


def _make_app() -> FastAPI:
    """GET /ping だけを返す小さな app を作る。"""
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """疎通の確認に応答する。"""
        return {"status": "ok"}

    return app


def _error_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """アプリ（voice_paste）が出した ERROR のログを返す。"""
    return [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR and record.name.startswith("voice_paste")
    ]


@pytest.fixture
def runners() -> Iterator[list[ApiServerRunner]]:
    """テストで作った ApiServerRunner を、テストの後に止める。"""
    created: list[ApiServerRunner] = []
    yield created
    for runner in created:
        runner.stop()


def test_start(runners: list[ApiServerRunner]) -> None:
    """空きポートなら待ち受けを始める（正常系）。"""
    from voice_paste.server.runner import ApiServerRunner

    # 準備
    port = _free_port()
    runner = ApiServerRunner(_make_app(), port)
    runners.append(runner)

    # 実行
    started = runner.start(START_TIMEOUT_SEC)

    # 検証
    assert started is True
    response = httpx.get(f"http://{LOOPBACK}:{port}/ping", timeout=REQUEST_TIMEOUT_SEC)
    assert response.status_code == 200


def test_start_when_port_in_use(
    runners: list[ApiServerRunner], caplog: pytest.LogCaptureFixture
) -> None:
    """ポートが使われていれば False（正常系）。"""
    from voice_paste.server.runner import ApiServerRunner

    # 準備
    caplog.set_level(logging.ERROR)
    port = _free_port()
    runner = ApiServerRunner(_make_app(), port)
    runners.append(runner)

    # 実行・検証
    with socket.socket() as occupier:
        occupier.bind((LOOPBACK, port))
        occupier.listen()
        started = runner.start(START_TIMEOUT_SEC)
    assert started is False
    assert len(_error_logs(caplog)) == 1


def test_stop(runners: list[ApiServerRunner]) -> None:
    """止めるとポートが空く（正常系）。"""
    from voice_paste.server.runner import ApiServerRunner

    # 準備
    port = _free_port()
    runner = ApiServerRunner(_make_app(), port)
    runners.append(runner)
    assert runner.start(START_TIMEOUT_SEC) is True

    # 実行
    runner.stop()

    # 検証
    assert not runner._thread.is_alive()
    with socket.socket() as reopened:
        reopened.bind((LOOPBACK, port))


def test_stop_when_not_started() -> None:
    """始めていなければ何もしない（正常系）。"""
    from voice_paste.server.runner import ApiServerRunner

    # 準備
    runner = ApiServerRunner(_make_app(), _free_port())

    # 実行・検証
    runner.stop()
