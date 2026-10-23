"""server の単体テスト用の組み立て。守りを通る要求のヘッダーと、SessionManager・ブラウザの音声のキューを Mock にした app を作る。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pydantic import SecretStr

PORT = 47823
TOKEN = "test-token-value"
CALLBACK_URL = "http://127.0.0.1:9000/result"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}
WEB_ORIGIN = "https://voice.example.com"
"""設定の許す Origin（api.allowed_web_origins）に入れる、ゲートウェイの公開のオリジン。"""


def _build_client(
    *, is_callback_allowed: bool, web_api: object
) -> tuple[TestClient, MagicMock]:
    """SessionManager を Mock にし、web_api を載せた app の TestClient（base_url は 127.0.0.1:{PORT}）と、その Mock を返す。"""
    from voice_paste.features.session.types import SessionApiDeps
    from voice_paste.server.app import build_fastapi

    session_manager = MagicMock()
    session_manager.start.return_value = SimpleNamespace(id="session-1")
    session_api = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=is_callback_allowed),
    )
    app = build_fastapi(
        session_api,
        SecretStr(TOKEN),
        PORT,
        web_api=web_api,
        allowed_web_origins=[WEB_ORIGIN],
    )
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}"), session_manager


def make_client(*, is_callback_allowed: bool = True) -> tuple[TestClient, MagicMock]:
    """SessionManager を Mock にした app の TestClient（base_url は 127.0.0.1:{PORT}）と、その Mock を返す。"""
    return _build_client(is_callback_allowed=is_callback_allowed, web_api=MagicMock())


def make_web_client(tmp_dir: Path) -> tuple[TestClient, MagicMock, MagicMock]:
    """ブラウザの音声のキューと形式の読み取りを Mock にした app の TestClient と、その 2 つの Mock を返す。

    形式の読み取り（probe_audio）は webm を返し、受けた音声は tmp_dir に書く。
    """
    from voice_paste.features.web_transcription.types import WebApiDeps
    from voice_paste.shared.types import AudioProbe

    queue = MagicMock()
    probe_audio = MagicMock(
        return_value=AudioProbe(container="webm", suffix=".webm", duration_sec=1.0, size_bytes=5)
    )
    web_api = WebApiDeps(queue=queue, probe_audio=probe_audio, tmp_dir=tmp_dir)
    client, _session_manager = _build_client(is_callback_allowed=True, web_api=web_api)
    return client, queue, probe_audio
