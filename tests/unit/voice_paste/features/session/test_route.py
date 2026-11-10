"""features/session/route.py（start_session_route）の単体テスト。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from voice_paste.shared.errors import CallbackNotAllowedError


def test_start_session_route_when_callback_not_allowed() -> None:
    """許されないコールバック先は開始しない（異常系）。"""
    from voice_paste.features.session.route import start_session_route
    from voice_paste.features.session.schemas import StartSessionRequest
    from voice_paste.features.session.types import SessionApiDeps

    # 準備
    session_manager = MagicMock()
    deps = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=False),
        glossary_preset_exists=MagicMock(return_value=True),
    )
    body = StartSessionRequest(callback_url="http://example.com/result")

    # 実行・検証
    with pytest.raises(CallbackNotAllowedError):
        start_session_route(body, deps)
    session_manager.start.assert_not_called()


@pytest.mark.parametrize(
    ("body", "expected_continuous"),
    [
        pytest.param(
            {"callback_url": "http://127.0.0.1:9000/r", "continuous": True},
            True,
            id="continuous",
        ),
        pytest.param({"callback_url": "http://127.0.0.1:9000/r"}, False, id="omitted"),
    ],
)
def test_start_session_route_when_continuous(
    body: dict[str, object], expected_continuous: bool
) -> None:
    """continuous を SessionManager.start へ渡す（正常系）。"""
    from voice_paste.features.session.route import start_session_route
    from voice_paste.features.session.schemas import StartSessionRequest
    from voice_paste.features.session.types import SessionApiDeps
    from voice_paste.shared.types import Entry

    # 準備
    session_manager = MagicMock()
    session_manager.start.return_value = SimpleNamespace(id="session-1")
    deps = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=True),
        glossary_preset_exists=MagicMock(return_value=True),
    )

    # 実行
    start_session_route(StartSessionRequest.model_validate(body), deps)

    # 検証
    session_manager.start.assert_called_once_with(
        entry=Entry.API,
        callback_url="http://127.0.0.1:9000/r",
        continuous=expected_continuous,
        glossary_preset=None,
    )


@pytest.mark.parametrize(
    ("body", "expected_glossary_preset", "expected_exists_calls"),
    [
        pytest.param(
            {"callback_url": "http://127.0.0.1:9000/r", "glossary_preset": "会議"},
            "会議",
            1,
            id="specified",
        ),
        pytest.param({"callback_url": "http://127.0.0.1:9000/r"}, None, 0, id="omitted"),
    ],
)
def test_start_session_route_when_glossary_preset(
    body: dict[str, object], expected_glossary_preset: str | None, expected_exists_calls: int
) -> None:
    """一覧にある用語集のプリセットを SessionManager.start へ渡す（正常系）。"""
    from voice_paste.features.session.route import start_session_route
    from voice_paste.features.session.schemas import StartSessionRequest
    from voice_paste.features.session.types import SessionApiDeps
    from voice_paste.shared.types import Entry

    # 準備（glossary_preset_exists は True を返す）
    session_manager = MagicMock()
    session_manager.start.return_value = SimpleNamespace(id="session-1")
    glossary_preset_exists = MagicMock(return_value=True)
    deps = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=True),
        glossary_preset_exists=glossary_preset_exists,
    )

    # 実行
    start_session_route(StartSessionRequest.model_validate(body), deps)

    # 検証（省いたときは glossary_preset_exists を呼ばない）
    session_manager.start.assert_called_once_with(
        entry=Entry.API,
        callback_url="http://127.0.0.1:9000/r",
        continuous=False,
        glossary_preset=expected_glossary_preset,
    )
    assert glossary_preset_exists.call_count == expected_exists_calls


def test_start_session_route_when_glossary_preset_not_found() -> None:
    """一覧に無い用語集のプリセットでは開始しない（異常系）。"""
    from voice_paste.features.session.route import start_session_route
    from voice_paste.features.session.schemas import StartSessionRequest
    from voice_paste.features.session.types import SessionApiDeps
    from voice_paste.shared.errors import GlossaryPresetNotFoundError

    # 準備（glossary_preset_exists は False を返す）
    session_manager = MagicMock()
    deps = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=MagicMock(return_value=True),
        glossary_preset_exists=MagicMock(return_value=False),
    )
    body = StartSessionRequest(
        callback_url="http://127.0.0.1:9000/r", glossary_preset="無い名前"
    )

    # 実行・検証
    with pytest.raises(GlossaryPresetNotFoundError, match="無い名前"):
        start_session_route(body, deps)
    session_manager.start.assert_not_called()
