"""出力先を追加するときに変える既存のモジュール（output_extensibility）の非機能要件テスト。

試しの出力先（設定のモデル・届ける関数・注入するものを選ぶ関数）を OUTPUTS の後ろへ登録しただけの一覧から、
main.py と同じ手順で設定のモデル（build_settings_model）・配線（_wire_outputs）・UiDeps を組み、
設定の読み書き・確定のホットキー・設定画面の欄・録音の画面のボタン・届けに乗ることを確かめる。
src/ のファイルは変えない。画面は offscreen の QApplication で開き、外部連携は Mock に差し替える。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal
from unittest.mock import MagicMock

from pydantic import Field
from PySide6.QtWidgets import QPushButton, QWidget

from tests.integration.ui.helpers import button_texts
from tests.unit.voice_paste.ui.helpers import OUTPUT_TITLES, make_ui_deps
from voice_paste.features.outputs import OUTPUTS, OutputDeps, OutputSpec, deliver
from voice_paste.main import _wire_outputs, build_hotkey_bindings
from voice_paste.shared.settings import (
    RELOAD_IMMEDIATE,
    OutputSettingsBase,
    build_settings_model,
    load_settings,
    save_settings,
)
from voice_paste.shared.types import Entry, TranscriptionOutcome
from voice_paste.ui.windows.recording_window import RecordingWindow
from voice_paste.ui.windows.settings_window import SettingsWindow

if TYPE_CHECKING:
    from collections.abc import Mapping

    from PySide6.QtWidgets import QApplication

TRIAL_ID = "try_output"
TRIAL_HOTKEY = "<ctrl>+<alt>+t"
TRIAL_DELAY_SEC = 1.0
TRIAL_TITLE = "試しの出力先"
TRIAL_INDEX = 3
"""試しの出力先が設定の outputs の何番目に入るか（OUTPUTS の設定のモデルを持つ 3 件の後ろ）。"""


class TrialOutputSettings(OutputSettingsBase):
    """試しの出力先の設定のモデル（ID・ホットキーと、出力先に固有の delay_sec）。"""

    id: Literal["try_output"] = Field(
        TRIAL_ID,
        description="出力先の ID（設定の outputs[] の判別子）",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    hotkey: str = Field(
        TRIAL_HOTKEY,
        description="この出力先で確定するホットキー",
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )
    delay_sec: float = Field(
        TRIAL_DELAY_SEC,
        description="試しの間（秒）",
        ge=0,
        json_schema_extra={"reload": RELOAD_IMMEDIATE},
    )


def _trial_handler(outcome: TranscriptionOutcome, target: str | None, *, write: object) -> None:
    """試しの出力先の届ける関数。起こした文字を、注入された書く関数へ渡す。"""
    assert callable(write)
    write(outcome.text)


def _trial_inject(deps: OutputDeps) -> Mapping[str, object]:
    """試しの出力先の注入するものを選ぶ関数。クリップボードへ書く関数だけを渡す。"""
    return {"write": deps.copy}


def _find_field(window: QWidget, key: str) -> QWidget | None:
    """設定画面の欄（項目 ID が `field_{キー}` か、ホットキーの欄の `hotkey_{キー}`）を引く。"""
    return window.findChild(QWidget, f"field_{key}") or window.findChild(QWidget, f"hotkey_{key}")


def test_output_extensibility(tmp_path: Path, qapp: QApplication) -> None:
    """試しの出力先を OUTPUTS の並びへの登録だけで追加すると、設定の読み書き・確定のホットキー・設定画面の欄・録音の画面のボタン・届けに乗る。"""
    # 準備: OUTPUTS の後ろに試しの出力先を追加した一覧から、main.py と同じ手順で設定のモデルを組む
    trial = OutputSpec(
        id=TRIAL_ID,
        title=TRIAL_TITLE,
        handler=_trial_handler,  # type: ignore[arg-type] 注入する関数は _wire_outputs が部分適用する
        settings_model=TrialOutputSettings,
        inject=_trial_inject,
    )
    outputs = (*OUTPUTS, trial)
    settings_model = build_settings_model(
        [spec.settings_model for spec in outputs if spec.settings_model is not None]
    )
    settings_file = tmp_path / "settings.toml"

    # 実行: 設定の読み書き（無ければ既定を書き、書いた設定を読み直し、保存して読み直す）
    load_settings(settings_file, settings_model)
    loaded = load_settings(settings_file, settings_model)
    save_settings(settings_file, loaded)
    reloaded = load_settings(settings_file, settings_model)

    # 検証: 読み直した設定の outputs の最後が試しの出力先（delay_sec 1.0）
    for settings in (loaded, reloaded):
        assert len(settings.outputs) == TRIAL_INDEX + 1
        assert isinstance(settings.outputs[-1], TrialOutputSettings)
        assert settings.outputs[-1].delay_sec == TRIAL_DELAY_SEC

    # 実行・検証: 確定のホットキー
    bindings = build_hotkey_bindings(reloaded, MagicMock(), MagicMock(), MagicMock())
    assert TRIAL_HOTKEY in bindings

    # 実行・検証: 設定画面の欄（試しの出力先の名前は UiDeps.output_titles から引く）
    ui_deps = make_ui_deps(
        tmp_path, settings=reloaded, output_titles={**OUTPUT_TITLES, TRIAL_ID: TRIAL_TITLE}
    )
    settings_window = SettingsWindow(ui_deps)
    try:
        for name in ("enabled", "hotkey", "delay_sec"):
            key = f"outputs[{TRIAL_INDEX}].{name}"
            assert _find_field(settings_window, key) is not None, f"{key} の欄が無い"
    finally:
        settings_window.close_without_confirm()

    # 実行・検証: 録音の画面のボタン
    recording_window = RecordingWindow(ui_deps)
    try:
        recording_window.open()
        button = recording_window.findChild(QPushButton, f"output_button_{TRIAL_ID}")
        assert button is not None
        assert button_texts(button) == [TRIAL_TITLE, "Ctrl+Alt+T"]
    finally:
        recording_window.close_window()

    # 実行・検証: 届け（試しの handler が inject の渡したものと共に呼ばれる）
    deps = OutputDeps(
        copy=MagicMock(),
        paste=MagicMock(),
        send_enter=MagicMock(),
        sleep=MagicMock(),
        jitter=MagicMock(),
        post=MagicMock(),
        get_settings=lambda: reloaded,
        notify_copied=MagicMock(),
    )
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )
    deliver(
        Entry.HOTKEY,
        TRIAL_ID,
        None,
        None,
        outcome,
        enabled_ids=frozenset({TRIAL_ID}),
        outputs=_wire_outputs(deps, outputs),
        preset_kinds=(),
    )
    deps.copy.assert_called_once_with("テスト")
