"""ui の単体テスト用の偽物と組み立て。

UiDeps の関数は全て Mock に、経過の時計は進められる時計に差し替える。
画面・トレイの組み立て（引数）はここに集め、テスト本体は組み立ての形を知らずに済ませる。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from voice_paste.features.session.types import Session
    from voice_paste.shared.settings import Preset, Settings
    from voice_paste.ui.controller import UiDeps
    from voice_paste.ui.tray import Tray

SESSION_STARTED_AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

OUTPUT_TITLES = {
    "paste_and_send": "貼り付けて送信",
    "paste_only": "貼り付けのみ",
    "copy_only": "コピーのみ",
}
"""画面に出す出力先の名前（出力先の ID → 名前。API 専用の出力先を除く）。"""


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
    """全ての関数を Mock にした UiDeps を作る。settings は get_settings が返す設定（既定は既定の出力先を持つ設定）、overrides は項目ごとの差し替え。"""
    from voice_paste.main import SETTINGS_MODEL
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.ui.controller import UiDeps as UiDepsModel

    fields: dict[str, Any] = {
        "start": MagicMock(return_value=None),
        "pause": MagicMock(return_value=None),
        "resume": MagicMock(return_value=None),
        "complete": MagicMock(return_value=None),
        "cancel": MagicMock(return_value=None),
        "current_session": MagicMock(return_value=None),
        "level": MagicMock(return_value=0.0),
        "get_settings": MagicMock(return_value=settings or SETTINGS_MODEL()),
        "save_settings": MagicMock(return_value=False),
        "settings_dir": tmp_path,
        "log_dir": tmp_path / "log",
        "request_restart": MagicMock(return_value=None),
        "request_quit": MagicMock(return_value=None),
        "suspend_hotkeys": MagicMock(return_value=None),
        "resume_hotkeys": MagicMock(return_value=None),
        "output_titles": OUTPUT_TITLES,
        "list_glossaries": MagicMock(
            return_value=[GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")]
        ),
        "read_glossary": MagicMock(return_value=[]),
        "new_glossary_path": MagicMock(return_value=tmp_path / "glossaries" / "glossary_1.csv"),
        "copy": MagicMock(return_value=None),
    }
    if "apply_theme" in {field.name for field in dataclasses.fields(UiDepsModel)}:
        fields["apply_theme"] = MagicMock(return_value=None)
    if "switch_output" in {field.name for field in dataclasses.fields(UiDepsModel)}:
        fields["switch_output"] = MagicMock(return_value=None)
    fields.update(overrides)
    return UiDepsModel(**fields)


def make_tray(tmp_path: Path) -> Tray:
    """設定とログのフォルダを一時フォルダの下にしたトレイを作る。"""
    from voice_paste.ui.tray import Tray as TrayWidget

    return TrayWidget(settings_dir=tmp_path, log_dir=tmp_path / "log")


def make_session(
    entry: str,
    state: str,
    *,
    output_id: str | None = None,
    output_preset: Preset | None = None,
) -> Session:
    """入口と状態を指定した Session を作る。output_id・output_preset は確定で選んだ固定の出力先の ID とカスタムプリセット。"""
    from voice_paste.features.session.types import Session as SessionModel
    from voice_paste.features.session.types import SessionState
    from voice_paste.shared.types import Entry

    return SessionModel(
        id="session-1",
        entry=Entry(entry),
        state=SessionState(state),
        started_at=SESSION_STARTED_AT,
        callback_url=None,
        output_id=output_id,
        output_preset=output_preset,
    )
