"""integrations/haas/server.py（HaasServer.ensure_started・stop）の単体テスト。

送信先は httpx.MockTransport に、wsl.exe の起動と時計は偽物に差し替える。
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from voice_paste.shared.errors import EngineError

PORT = 47824
TICK_SEC = 1.0

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """呼ぶたびに進む時計。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        """今の時刻を返して進める。"""
        self.now += TICK_SEC
        return self.now


@pytest.fixture(autouse=True)
def no_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """応答の確認の間隔を 0 にする。"""
    monkeypatch.setattr("voice_paste.integrations.haas.server.HAAS_HEALTH_INTERVAL_SEC", 0.0)


def _ready() -> httpx.Response:
    """/health の応答を返す。"""
    return httpx.Response(200, json={"ok": True, "model": "m"})


def _health(*steps: bool) -> Handler:
    """/health に台本（True は応答・False は接続エラー）を順に当て（尽きたら最後を繰り返す）、ほかは 202 を返す。"""
    script: Iterator[bool] = iter(steps)
    last = {"step": steps[0]}

    def handler(request: httpx.Request) -> httpx.Response:
        """/health は台本のとおり、ほかは 202。"""
        if request.url.path != "/health":
            return httpx.Response(202)
        last["step"] = next(script, last["step"])
        if not last["step"]:
            raise httpx.ConnectError("refused")
        return _ready()

    return handler


def _make_server(handler: Handler, *, distribution: str = "Ubuntu-24.04") -> tuple[Any, MagicMock]:
    """差し替えた HaasServer と wsl.exe の起動の偽物を返す。"""
    from voice_paste.integrations.haas.server import HaasServer
    from voice_paste.shared.settings import HaasSettings

    popen = MagicMock()
    popen.return_value.poll.return_value = None
    server = HaasServer(
        settings=HaasSettings(distribution=distribution, port=PORT),
        popen=popen,
        clock=FakeClock(),
        transport=httpx.MockTransport(handler),
    )
    return server, popen


def test_ensure_started_when_already_running() -> None:
    """接続先が応答すれば起動しない（正常系）。"""
    # 準備
    paths: list[str] = []
    inner = _health(True)

    def handler(request: httpx.Request) -> httpx.Response:
        """パスを覚えて台本へ渡す。"""
        paths.append(request.url.path)
        return inner(request)

    server, popen = _make_server(handler)

    # 実行
    server.ensure_started()
    server.stop()

    # 検証
    popen.assert_not_called()
    assert "/shutdown" not in paths


def test_ensure_started_when_not_running() -> None:
    """応答が無ければ起動して応答を待つ（正常系）。"""
    from voice_paste.integrations.haas.server import HAAS_SERVER_DIR

    # 準備
    server, popen = _make_server(_health(False, True))

    # 実行
    server.ensure_started()

    # 検証
    assert popen.call_args.args[0] == [
        "wsl.exe",
        "-d",
        "Ubuntu-24.04",
        "--cd",
        str(HAAS_SERVER_DIR),
        "-e",
        "bash",
        "start.sh",
        "47824",
    ]


def test_ensure_started_when_default_distribution() -> None:
    """ディストリビューションが空なら -d を付けない（正常系）。"""
    # 準備
    server, popen = _make_server(_health(False, True), distribution="")

    # 実行
    server.ensure_started()

    # 検証
    assert "-d" not in popen.call_args.args[0]


def test_ensure_started_when_wsl_missing() -> None:
    """wsl.exe を起動できない（異常系）。"""
    # 準備
    server, popen = _make_server(_health(False))
    popen.side_effect = FileNotFoundError("wsl.exe")

    # 実行・検証
    with pytest.raises(EngineError):
        server.ensure_started()


def test_ensure_started_when_script_failed() -> None:
    """起動スクリプトが失敗して終わる（異常系）。"""
    # 準備
    server, popen = _make_server(_health(False))
    popen.return_value.poll.return_value = 1

    # 実行・検証
    with pytest.raises(EngineError):
        server.ensure_started()


def test_ensure_started_when_timeout() -> None:
    """待ち時間までに応答が無い（異常系）。"""
    # 準備
    server, popen = _make_server(_health(False))

    # 実行・検証
    with pytest.raises(EngineError):
        server.ensure_started()
    popen.return_value.terminate.assert_called_once()


def test_stop() -> None:
    """起動したサーバーを止める（正常系）。"""
    # 準備
    calls: list[tuple[str, str]] = []
    inner = _health(False, True)

    def handler(request: httpx.Request) -> httpx.Response:
        """方法とパスを覚えて台本へ渡す。"""
        calls.append((request.method, request.url.path))
        return inner(request)

    server, popen = _make_server(handler)
    server.ensure_started()

    # 実行
    server.stop()

    # 検証
    assert calls.count(("POST", "/shutdown")) == 1
    popen.return_value.terminate.assert_not_called()


def test_stop_when_unreachable() -> None:
    """/shutdown が届かなくても例外を出さず、wsl.exe を終わらせる（正常系）。"""
    # 準備
    inner = _health(False, True)

    def handler(request: httpx.Request) -> httpx.Response:
        """/shutdown は接続エラー、/health は台本のとおり。"""
        if request.url.path == "/shutdown":
            raise httpx.ConnectError("refused")
        return inner(request)

    server, popen = _make_server(handler)
    server.ensure_started()

    # 実行
    server.stop()

    # 検証
    popen.return_value.terminate.assert_called_once()


def test_stop_when_loading() -> None:
    """起動の待ちの間に止めると wsl.exe を終わらせる（正常系）。"""
    # 準備（2 回目の /health の間に別スレッドから stop を呼ぶ）
    holder: dict[str, Any] = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """/health も /shutdown も接続エラー。"""
        if request.url.path == "/health":
            holder["count"] += 1
            if holder["count"] == 2:
                stopper = threading.Thread(target=holder["server"].stop)
                stopper.start()
                stopper.join()
        raise httpx.ConnectError("refused")

    holder["server"], popen = _make_server(handler)

    # 実行・検証
    with pytest.raises(EngineError):
        holder["server"].ensure_started()
    popen.return_value.terminate.assert_called()
