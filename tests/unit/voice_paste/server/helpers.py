"""server の単体テスト用の組み立て。守りを通る要求のヘッダーと、SessionManager を Mock にした app を作る。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pydantic import SecretStr

PORT = 47823
TOKEN = "test-token-value"
CALLBACK_URL = "http://127.0.0.1:9000/result"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}


def make_client(*, is_callback_allowed: bool = True) -> tuple[TestClient, MagicMock]:
    """SessionManager を Mock にした app の TestClient（base_url は 127.0.0.1:{PORT}）と、その Mock を返す。"""
    from voice_paste.features.session.types import SessionApiDeps
    from voice_paste.server.app import build_fastapi

    session_manager = MagicMock()
    session_manager.start.return_value = SimpleNamespace(id="session-1")
    session_api = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=is_callback_allowed),
    )
    app = build_fastapi(session_api, SecretStr(TOKEN), PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}"), session_manager
