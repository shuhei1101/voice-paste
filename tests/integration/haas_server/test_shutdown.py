"""停止する（POST /shutdown）の結合テスト。

サーバーを別のプロセスで起動し、Haas のモデルの読み込みを偽物に差し替える（GPU を使わない）。
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from tests.integration.haas_server.helpers import FAKE_TEXT, make_wav
from tests.integration.helpers import wait_until
from tests.support.real_service import free_port

EXIT_WAIT_SEC = 30.0
START_WAIT_SEC = 30.0
WAV_SECONDS = 1


@dataclass
class Server:
    """別のプロセスで動くサーバー。"""

    process: subprocess.Popen[bytes]
    url: str
    work_dir: Path
    log_file: Path


def _responds(url: str) -> bool:
    """GET /health に接続できるかを返す。"""
    try:
        return httpx.get(f"{url}/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    """偽のモデルのサーバーを別のプロセスで起動し、テストの後に残っていれば終わらせる。"""
    port = free_port()
    log_file = tmp_path / "haas_server.log"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.integration.haas_server.fake_server",
            str(port),
            str(log_file),
            str(tmp_path),
        ]
    )
    url = f"http://127.0.0.1:{port}"
    assert wait_until(lambda: _responds(url), START_WAIT_SEC)

    yield Server(process, url, tmp_path, log_file)

    (tmp_path / "released").touch()
    if process.poll() is None:
        process.terminate()
    process.wait(EXIT_WAIT_SEC)


def test_normal(server: Server) -> None:
    """停止を受け付けて 202 を返し、プロセスを終える（正常系）。"""
    # 実行
    response = httpx.post(f"{server.url}/shutdown")

    # 検証
    assert response.status_code == 202
    assert server.process.wait(EXIT_WAIT_SEC) == 0
    assert not _responds(server.url)


def test_normal_when_transcribing(server: Server) -> None:
    """起こしている要求の応答を返し終えてから終わる（正常系）。"""
    # 準備（起こしている要求をモデルで待たせる）
    responses: list[httpx.Response] = []

    def post_audio() -> None:
        """音声を送信し、応答を記録する。"""
        responses.append(
            httpx.post(
                f"{server.url}/transcriptions",
                files={"audio": ("audio.wav", make_wav(WAV_SECONDS))},
                timeout=EXIT_WAIT_SEC,
            )
        )

    sender = threading.Thread(target=post_audio)
    sender.start()
    assert wait_until((server.work_dir / "started").exists, START_WAIT_SEC)

    # 実行
    shutdown = httpx.post(f"{server.url}/shutdown")
    (server.work_dir / "released").touch()
    sender.join(EXIT_WAIT_SEC)

    # 検証
    assert shutdown.status_code == 202
    assert responses[0].status_code == 200
    assert responses[0].json() == {"text": FAKE_TEXT}
    assert server.process.wait(EXIT_WAIT_SEC) == 0


def test_error_when_origin_not_allowed(server: Server) -> None:
    """Origin が付いた停止の要求を断り、サーバーは動き続ける（異常系）。"""
    # 実行
    response = httpx.post(f"{server.url}/shutdown", headers={"Origin": "http://evil.example"})

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert _responds(server.url)
    assert server.process.poll() is None
    assert "evil.example" in server.log_file.read_text(encoding="utf-8")
