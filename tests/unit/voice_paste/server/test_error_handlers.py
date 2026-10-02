"""server/error_handlers.py（register_exception_handlers）の単体テスト。

build_fastapi が登録した例外ハンドラを、SessionManager を Mock にした app へ要求を送って確かめる。
"""

from __future__ import annotations

from tests.unit.voice_paste.server.helpers import AUTHORIZATION, CALLBACK_URL, make_client
from voice_paste.shared.errors import SessionBusyError


def test_register_exception_handlers_when_validation_error() -> None:
    """URI でない callback_url は 400（正常系）。"""
    # 準備
    client, _session_manager = make_client()

    # 実行
    response = client.post("/sessions", json={"callback_url": "nope"}, headers=AUTHORIZATION)

    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_register_exception_handlers_when_busy() -> None:
    """SessionBusyError は 409（正常系）。"""
    # 準備
    client, session_manager = make_client()
    session_manager.start.side_effect = SessionBusyError("処理中")

    # 実行
    response = client.post(
        "/sessions", json={"callback_url": CALLBACK_URL}, headers=AUTHORIZATION
    )

    # 検証
    assert response.status_code == 409
