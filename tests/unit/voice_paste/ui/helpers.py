"""ui の単体テスト用の偽物と組み立て。

UiDeps の関数は全て Mock に、経過の時計は進められる時計に差し替える。
画面・トレイの組み立て（引数）はここに集め、テスト本体は組み立ての形を知らずに済ませる。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from voice_paste.features.session.types import Session
    from voice_paste.shared.settings import Settings
    from voice_paste.ui.controller import UiDeps
    from voice_paste.ui.tray import Tray

SESSION_STARTED_AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


class FakeClock:
    """進められる経過の時計（秒）。文字起こし中の表示の clock に渡す。"""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        """今の時刻（秒）を返す。"""
        return self.now


def make_ui_deps(
    tmp_path: Path, *, settings: Settings | None = None, **overrides: Any
) -> UiDeps:
    """全ての関数を Mock にした UiDeps を作る。settings は get_settings が返す設定、overrides は項目ごとの差し替え。"""
    from voice_paste.shared.settings import Settings as SettingsModel
    from voice_paste.ui.controller import UiDeps as UiDepsModel

    fields: dict[str, Any] = {
        "start": MagicMock(return_value=None),
        "pause": MagicMock(return_value=None),
        "resume": MagicMock(return_value=None),
        "complete": MagicMock(return_value=None),
        "cancel": MagicMock(return_value=None),
        "current_session": MagicMock(return_value=None),
        "level": MagicMock(return_value=0.0),
        "get_settings": MagicMock(return_value=settings or SettingsModel()),
        "save_settings": MagicMock(return_value=False),
        "settings_dir": tmp_path,
        "log_dir": tmp_path / "log",
        "request_restart": MagicMock(return_value=None),
        "request_quit": MagicMock(return_value=None),
        "suspend_hotkeys": MagicMock(return_value=None),
        "resume_hotkeys": MagicMock(return_value=None),
    }
    fields.update(overrides)
    return UiDepsModel(**fields)


def make_tray(tmp_path: Path) -> Tray:
    """設定とログのフォルダを一時フォルダの下にしたトレイを作る。"""
    from voice_paste.ui.tray import Tray as TrayWidget

    return TrayWidget(settings_dir=tmp_path, log_dir=tmp_path / "log")


def make_session(entry: str, state: str) -> Session:
    """入口と状態を指定した Session を作る。"""
    from voice_paste.features.session.types import Session as SessionModel
    from voice_paste.features.session.types import SessionState
    from voice_paste.shared.types import Entry

    return SessionModel(
        id="session-1",
        entry=Entry(entry),
        state=SessionState(state),
        started_at=SESSION_STARTED_AT,
        callback_url=None,
        output_id=None,
        output_target=None,
    )
