"""features/session/route.py（start_session_route）の単体テスト。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from voice_paste.shared.errors import CallbackNotAllowedError


def test_start_session_route_when_callback_not_allowed() -> None:
    """許されない返送先は開始しない（異常系）。"""
    from voice_paste.features.session.route import start_session_route
    from voice_paste.features.session.schemas import StartSessionRequest
    from voice_paste.features.session.types import SessionApiDeps

    # 準備
    session_manager = MagicMock()
    deps = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=False),
    )
    body = StartSessionRequest(callback_url="http://example.com/result")

    # 実行・検証
    with pytest.raises(CallbackNotAllowedError):
        start_session_route(body, deps)
    session_manager.start.assert_not_called()
