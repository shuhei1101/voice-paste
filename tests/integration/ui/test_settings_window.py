"""画面設計「設定画面」「変えた値を捨てる確認」「既定に戻す確認」を元にした結合テスト。

本物の設定画面を offscreen で開き、UiDeps は差し替えた関数で受ける。
欄は項目 ID（`field_{キー}`・`hotkey_{キー}` など）で引き、操作は QtTest で行う。
モーダルの確認ダイアログは exec で止まるため、ModalDriver が押すボタンを予約する。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRegularExpression, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QAbstractButton,
    QPushButton,
    QRadioButton,
    QSlider,
    QWidget,
)

from tests.integration.ui.helpers import ModalDriver, Ui, find, make_ui_deps, no_modal
from voice_paste.main import SETTINGS_MODEL

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Settings
    from voice_paste.ui.controller import UiDeps
    from voice_paste.ui.windows.settings_window import SettingsWindow

RESTART_KEY = "transcription.local_whisper.beam_size"
"""反映が restart の数値の欄（再起動で反映の印・再起動の知らせの確かめに使う）。"""

IMMEDIATE_KEY = "recording.fade_sec"
"""反映が immediate の数値の欄。"""


@dataclass
class Opened:
    """開いた設定画面と、渡した UiDeps、窓が閉じた・保存した・再起動を頼んだ回数を覚える Mock。"""

    window: SettingsWindow
    deps: UiDeps
    closed: MagicMock
    saved: MagicMock
    restart_requested: MagicMock


@pytest.fixture
def open_window(qapp: QApplication, tmp_path: Path) -> Iterator[Callable[..., Opened]]:
    """設定（無ければ既定）で設定画面を開く関数を返す。テストの後に窓を隠す。"""
    from voice_paste.ui.windows.settings_window import SettingsWindow

    windows: list[SettingsWindow] = []

    def _open(settings: Settings | None = None, **deps_overrides: object) -> Opened:
        """設定画面を開き、窓の Signal を Mock につなぐ。"""
        deps = make_ui_deps(tmp_path, settings=settings, **deps_overrides)
        window = SettingsWindow(deps)
        windows.append(window)
        opened = Opened(window, deps, MagicMock(), MagicMock(), MagicMock())
        window.closed.connect(opened.closed)
        window.saved.connect(opened.saved)
        window.restart_requested.connect(opened.restart_requested)
        window.show()
        return opened

    yield _open
    for window in windows:
        window.hide()


def _field(window: QWidget, key: str, cls: type = QWidget) -> Any:
    """設定のキーの欄を引く（ホットキーの欄は `hotkey_{キー}`、それ以外は `field_{キー}`）。"""
    found = window.findChild(cls, f"field_{key}") or window.findChild(cls, f"hotkey_{key}")
    assert found is not None, f"{key} の欄が無い"
    return found


def _set_text(window: QWidget, key: str, text: str) -> None:
    """文字の欄に文字を入れる。"""
    _field(window, key, QLineEdit).setText(text)


def _press(window: QWidget, key: str, key_code: Qt.Key, modifiers: Qt.KeyboardModifier) -> None:
    """ホットキーの欄にキーの組み合わせを押す。"""
    edit = _field(window, key)
    edit.setFocus()
    QTest.keyClick(edit, key_code, modifiers)


def _click(window: QWidget, name: str) -> None:
    """ボタンを押す。"""
    QTest.mouseClick(find(window, QPushButton, name), Qt.MouseButton.LeftButton)


def _error_rows(window: QWidget) -> list[str]:
    """エラーの一覧の行（QLabel の文字）を、リンクの書式を外して並べる。"""
    from PySide6.QtGui import QTextDocument

    summary = find(window, QFrame, "error_summary")
    rows = []
    for label in summary.findChildren(QLabel):
        # 書式を解釈しないラベルは文字のまま、リンクのラベルは書式を外して読む
        if label.textFormat() == Qt.TextFormat.PlainText:
            rows.append(label.text())
            continue
        document = QTextDocument()
        document.setHtml(label.text())
        rows.append(document.toPlainText())
    return rows


def _field_errors(window: QWidget) -> list[str]:
    """欄の下（行の下）に出ているエラーの文を並べる。"""
    return [
        label.text()
        for label in window.findChildren(QLabel)
        if label.property("role") == "error" and not label.isHidden()
    ]


def _panel(window: QWidget, kind: str) -> QWidget:
    """種類のタブのプリセットの一覧（`preset_list_{kind}`）を引く。"""
    return find(window, QWidget, f"preset_list_{kind}")


def _preset_field(window: QWidget, kind: str, number: int, attribute: str, cls: type = QWidget) -> Any:
    """種類のタブの number 件目のプリセットの欄（`preset_{項目}_{n}`）を引く。"""
    found = _panel(window, kind).findChild(cls, f"preset_{attribute}_{number}")
    assert found is not None, f"{kind} の {number} 件目の {attribute} の欄が無い"
    return found


def _add_preset(window: QWidget, kind: str, title: str, url: str) -> int:
    """種類のタブの「プリセットを足す」を押し、足した行にタイトルと URL を入れて、その行の番号を返す。"""
    QTest.mouseClick(find(window, QPushButton, f"add_preset_button_{kind}"), Qt.MouseButton.LeftButton)
    number = len(_panel(window, kind).findChildren(QLineEdit, QRegularExpression("^preset_title_"))) - 1
    _preset_field(window, kind, number, "title", QLineEdit).setText(title)
    _preset_field(window, kind, number, "url", QLineEdit).setText(url)
    return number


def _label_with_text(window: QWidget, text: str) -> QLabel:
    """文字が text に一致するラベルを引く。"""
    found = [label for label in window.findChildren(QLabel) if label.text() == text]
    assert len(found) == 1, f"「{text}」のラベルが 1 つでない"
    return found[0]


def _top_of(widget: QWidget, window: QWidget) -> int:
    """部品の上端の、窓の中での y 座標を返す。"""
    return widget.mapTo(window, QPoint(0, 0)).y()


def _left_of(widget: QWidget, window: QWidget) -> int:
    """部品の左端の、窓の中での x 座標を返す。"""
    return widget.mapTo(window, QPoint(0, 0)).x()


def _leaf_keys(settings: Settings) -> list[str]:
    """設定のキー（outputs・presets の中は除く）を、ドット区切りで全て並べる。"""
    from pydantic import BaseModel

    keys: list[str] = []

    def _walk(model: BaseModel, prefix: str) -> None:
        """入れ子のモデルを辿り、末端の項目のキーを集める。"""
        for name in type(model).model_fields:
            value = getattr(model, name)
            key = f"{prefix}{name}"
            if isinstance(value, BaseModel):
                _walk(value, f"{key}.")
            elif name not in ("outputs", "presets"):
                keys.append(key)

    _walk(settings, "")
    return keys


# === settings_window ===


def test_settings_window_title_and_width(open_window: Callable[..., Opened]) -> None:
    """窓の題は「voice-paste の設定」で、最小の幅は 720px。"""
    # 実行
    opened = open_window()

    # 検証
    assert opened.window.windowTitle() == "voice-paste の設定"
    assert opened.window.minimumWidth() == 720


def test_settings_window_initial_value(open_window: Callable[..., Opened]) -> None:
    """開いたときの settings.toml の値を欄に入れる。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.shared.settings import HistorySettings, HotkeySettings, RecordingSettings, Settings, UiSettings

    # 準備
    settings = SETTINGS_MODEL(
        recording=RecordingSettings(fade_sec=1.5, hide_window=True, volume_percent=35),
        ui=UiSettings(position="top-left"),
        hotkeys=HotkeySettings(start="<ctrl>+<alt>+s"),
        history=HistorySettings(retention_days=3),
        outputs=[
            PasteAndSendSettings(enabled=False, enter_delay_sec=0.8),
            PasteOnlySettings(),
            CopyOnlySettings(),
        ],
    )

    # 実行
    window = open_window(settings).window

    # 検証
    assert _field(window, "recording.fade_sec", QLineEdit).text() == "1.5"
    assert _field(window, "recording.hide_window", QCheckBox).isChecked()
    assert _field(window, "recording.volume_percent", QSlider).value() == 35
    assert _field(window, "history.retention_days", QLineEdit).text() == "3"
    assert _field(window, "hotkeys.start", QLineEdit).text() == "Ctrl+Alt+S"
    assert not _field(window, "outputs[0].enabled", QCheckBox).isChecked()
    assert _field(window, "outputs[0].enter_delay_sec", QLineEdit).text() == "0.8"
    position = _field(window, "ui.position")
    checked = [b.text() for b in position.findChildren(QRadioButton) if b.isChecked()]
    assert checked == ["top-left"]


# === group_menu ===


def test_group_menu_initial(open_window: Callable[..., Opened]) -> None:
    """まとまりのメニューは、出力先・ブラウザ添付・エンドポイントへ送る・ホットキー・録音・文字起こし・画面・履歴とログ・API の順で、既定は出力先。"""
    # 実行
    window = open_window().window

    # 検証
    menu = find(window, QListWidget, "group_menu")
    names = [menu.item(row).text() for row in range(menu.count())]
    assert names == [
        "出力先",
        "ブラウザ添付",
        "エンドポイントへ送る",
        "ホットキー",
        "録音",
        "文字起こし",
        "画面",
        "履歴とログ",
        "API",
    ]
    assert menu.currentRow() == 0
    assert _field(window, "outputs[0].enabled").isVisible()


@pytest.mark.parametrize(
    ("row", "shown_key", "hidden_key"),
    [
        (1, "preset_options.browser.open_delay_sec", "outputs[0].enabled"),
        (2, "preset_options.endpoint.timeout_sec", "preset_options.browser.open_delay_sec"),
        (3, "hotkeys.start", "preset_options.endpoint.timeout_sec"),
        (4, "recording.fade_sec", "hotkeys.start"),
        (5, "transcription.local_whisper.model", "recording.fade_sec"),
        (6, "ui.wave_gain", "transcription.local_whisper.model"),
        (7, "history.retention_days", "ui.wave_gain"),
        (8, "api.port", "history.retention_days"),
        (0, "outputs[0].enabled", "api.port"),
    ],
)
def test_group_menu_action(
    open_window: Callable[..., Opened], row: int, shown_key: str, hidden_key: str
) -> None:
    """まとまりを選ぶと、右の欄をそのまとまりに切り替える（欄はそのまとまりを選んだときだけ出る）。"""
    # 準備
    window = open_window().window

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(row)

    # 検証
    assert _field(window, shown_key).isVisible()
    assert not _field(window, hidden_key).isVisible()


def test_group_menu_keeps_values(open_window: Callable[..., Opened]) -> None:
    """切り替えても入れた値は消さない。"""
    # 準備
    window = open_window().window
    menu = find(window, QListWidget, "group_menu")
    menu.setCurrentRow(4)
    _set_text(window, IMMEDIATE_KEY, "1.25")

    # 実行
    menu.setCurrentRow(8)
    menu.setCurrentRow(4)

    # 検証
    assert _field(window, IMMEDIATE_KEY, QLineEdit).text() == "1.25"


# === field_{key}・restart_badge_{key} ===


def test_field_for_every_setting_key(open_window: Callable[..., Opened]) -> None:
    """settings.toml の全てのキーに欄がある（項目を足しても画面の直しが増えない）。"""
    from voice_paste.shared.settings import Settings

    # 実行
    window = open_window().window

    # 検証
    for key in _leaf_keys(SETTINGS_MODEL()):
        assert window.findChild(QWidget, f"field_{key}") or window.findChild(
            QWidget, f"hotkey_{key}"
        ), f"{key} の欄が無い"


@pytest.mark.parametrize(
    ("key", "cls"),
    [
        ("recording.lower_volume", QCheckBox),
        ("recording.volume_percent", QSlider),
        ("recording.fade_sec", QLineEdit),
        ("api.port", QLineEdit),
        ("api.allowed_callback_hosts", QPlainTextEdit),
        ("transcription.engine", QComboBox),
        ("transcription.local_whisper.model", QComboBox),
        ("transcription.local_whisper.language", QLineEdit),
        ("glossary_path", QLineEdit),
    ],
)
def test_field_widget_type(open_window: Callable[..., Opened], key: str, cls: type) -> None:
    """欄の部品は設定のモデルの型から決める（bool はチェックボックス・数値と文字は文字の欄・つまみ・選択の欄など）。"""
    # 実行
    window = open_window().window

    # 検証
    assert isinstance(_field(window, key), cls)


@pytest.mark.parametrize(
    ("key", "choices"),
    [
        ("ui.position", ["center", "top-left", "top-right", "bottom-left", "bottom-right"]),
        ("logging.level", ["DEBUG", "INFO", "WARNING", "ERROR"]),
        ("transcription.local_whisper.device", ["cuda", "cpu"]),
    ],
)
def test_field_widget_type_when_literal(
    open_window: Callable[..., Opened], key: str, choices: list[str]
) -> None:
    """リテラルの列挙の項目は、選択肢ごとのラジオボタンにする。"""
    # 実行
    window = open_window().window

    # 検証
    buttons = _field(window, key).findChildren(QRadioButton)
    assert [button.text() for button in buttons] == choices


def test_field_name_and_key(open_window: Callable[..., Opened]) -> None:
    """欄の名前（設定の項目の説明）と、欄の右に settings.toml のキーを出す。"""
    from voice_paste.shared.settings import ApiSettings

    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(8)
    name = (ApiSettings.model_fields["port"].description or "").split("。")[0]

    # 実行
    texts = [label.text() for label in window.findChildren(QLabel)]

    # 検証
    assert "api.port" in texts
    assert name in texts


def test_restart_badge_when_restart_field(open_window: Callable[..., Opened]) -> None:
    """反映が restart の欄には「再起動で反映」の印を出す。"""
    # 実行
    window = open_window().window

    # 検証
    badge = find(window, QLabel, f"restart_badge_{RESTART_KEY}")
    assert badge.text() == "再起動で反映"


def test_restart_badge_when_immediate_field(open_window: Callable[..., Opened]) -> None:
    """反映が immediate の欄には印を出さない。"""
    # 実行
    window = open_window().window

    # 検証
    assert window.findChild(QLabel, f"restart_badge_{IMMEDIATE_KEY}") is None


# === hotkey_{key} ===


def test_hotkey_field_initial_value(open_window: Callable[..., Opened]) -> None:
    """ホットキーの欄は、画面では `Ctrl+Alt+D` の形で出す。"""
    # 実行
    window = open_window().window

    # 検証
    assert _field(window, "hotkeys.start", QLineEdit).text() == "Ctrl+Alt+D"
    assert _field(window, "hotkeys.pause", QLineEdit).text() == "Ctrl+Alt+Z"


def test_hotkey_field_action(open_window: Callable[..., Opened]) -> None:
    """ホットキーの欄で押したキーの組み合わせが入り、保存では pynput の書式（`<ctrl>+<alt>+d`）で書く。"""
    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(3)

    # 実行
    _press(
        window,
        "hotkeys.start",
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )

    # 検証
    assert _field(window, "hotkeys.start", QLineEdit).text() == "Ctrl+Shift+S"
    assert window.collect()["hotkeys"]["start"] == "<ctrl>+<shift>+s"


def test_hotkey_field_when_modifier_only(open_window: Callable[..., Opened]) -> None:
    """修飾キーだけでは、組み合わせに入れない。"""
    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(3)

    # 実行
    _press(window, "hotkeys.start", Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)

    # 検証
    assert _field(window, "hotkeys.start", QLineEdit).text() == "Ctrl+Alt+D"


def test_hotkey_field_when_tab(open_window: Callable[..., Opened]) -> None:
    """Tab は欄の移動に残し、組み合わせに入れない。"""
    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(3)

    # 実行
    _press(window, "hotkeys.start", Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)

    # 検証
    assert _field(window, "hotkeys.start", QLineEdit).text() == "Ctrl+Alt+D"


def test_hotkey_field_when_escape(open_window: Callable[..., Opened]) -> None:
    """Esc は画面の取り消しに残し、組み合わせに入れない（欄を変えていなければ画面を閉じる）。"""
    # 準備
    opened = open_window()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(3)

    # 実行
    _press(opened.window, "hotkeys.start", Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)

    # 検証
    assert _field(opened.window, "hotkeys.start", QLineEdit).text() == "Ctrl+Alt+D"
    opened.closed.assert_called_once()


# === preset_list_{kind}・preset_empty_{kind}・add_preset_button_{kind} ===

KINDS = ("browser", "endpoint")
"""種類のタブ（ブラウザ添付・エンドポイントへ送る）の種類。"""


def _settings_with_presets() -> Settings:
    """ブラウザ添付 2 件とエンドポイントへ送る 1 件のプリセットを持つ設定を作る。"""
    from voice_paste.shared.settings import BrowserPreset, EndpointPreset, Settings

    return SETTINGS_MODEL(
        presets=[
            EndpointPreset(
                title="受け口",
                url="http://127.0.0.1:9000/hook",
                hotkey="<ctrl>+<alt>+4",
                authorization="Bearer x",
            ),
            BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1"),
            BrowserPreset(title="Claude", url="https://claude.ai/new", send_enter=False),
        ]
    )


@pytest.mark.parametrize(
    ("row", "kind", "other"),
    [(1, "browser", "endpoint"), (2, "endpoint", "browser")],
    ids=["browser", "endpoint"],
)
def test_preset_list_when_visible(
    open_window: Callable[..., Opened], row: int, kind: str, other: str
) -> None:
    """プリセットの一覧は、その種類のタブを選んだときだけ出る（もう一方の種類の一覧は出ない）。"""
    # 準備
    window = open_window().window
    assert not _panel(window, kind).isVisible()

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(row)

    # 検証
    assert _panel(window, kind).isVisible()
    assert not _panel(window, other).isVisible()
    assert find(window, QPushButton, f"add_preset_button_{kind}").isVisible()


@pytest.mark.parametrize(("kind", "name"), [("browser", "ブラウザ添付"), ("endpoint", "エンドポイントへ送る")])
def test_preset_empty_when_no_presets(open_window: Callable[..., Opened], kind: str, name: str) -> None:
    """プリセットが 1 件も無いタブには、足すと録音の画面にボタンが出ることを伝える案内を出す。"""
    # 準備
    window = open_window().window

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(KINDS.index(kind) + 1)

    # 検証
    empty = find(window, QLabel, f"preset_empty_{kind}")
    assert empty.isVisible()
    assert empty.text() == (
        f"{name}のプリセットはまだありません。足すと、録音の画面の「カスタムプリセット」にボタンが出ます。"
    )


def test_preset_list_initial_value(open_window: Callable[..., Opened]) -> None:
    """プリセットの一覧は、そのタブの種類のプリセットを設定の並びで 1 件ずつ並べ、案内は出さない。"""
    # 実行
    window = open_window(_settings_with_presets()).window
    find(window, QListWidget, "group_menu").setCurrentRow(1)

    # 検証（ブラウザ添付のタブ）
    assert [_preset_field(window, "browser", n, "title", QLineEdit).text() for n in range(2)] == [
        "ChatGPT",
        "Claude",
    ]
    assert _preset_field(window, "browser", 0, "url", QLineEdit).text() == "https://chatgpt.com"
    assert _preset_field(window, "browser", 0, "hotkey", QLineEdit).text() == "Ctrl+Alt+1"
    assert _preset_field(window, "browser", 1, "hotkey", QLineEdit).text() == ""
    assert _preset_field(window, "browser", 0, "send_enter", QCheckBox).isChecked()
    assert not _preset_field(window, "browser", 1, "send_enter", QCheckBox).isChecked()
    assert not find(window, QLabel, "preset_empty_browser").isVisible()
    # エンドポイントへ送るのタブ
    find(window, QListWidget, "group_menu").setCurrentRow(2)
    assert _preset_field(window, "endpoint", 0, "title", QLineEdit).text() == "受け口"
    assert _preset_field(window, "endpoint", 0, "hotkey", QLineEdit).text() == "Ctrl+Alt+4"


def test_preset_enabled_switch(open_window: Callable[..., Opened]) -> None:
    """有効の切り替えは、今の状態を文字（有効 / 無効）でも出し、足したプリセットはオン。"""
    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(1)
    _add_preset(window, "browser", "ChatGPT", "https://chatgpt.com")
    switch = _preset_field(window, "browser", 0, "enabled", QCheckBox)

    # 検証（足した直後）
    assert switch.isChecked()
    assert switch.text() == "有効"

    # 実行
    switch.setChecked(False)

    # 検証（切り替えた後）
    assert switch.text() == "無効"
    assert window.collect()["presets"][0]["enabled"] is False


def test_preset_authorization_field(open_window: Callable[..., Opened]) -> None:
    """Authorization の欄は伏せ字で、入れた文字を出さない。ブラウザ添付には出ない。"""
    # 準備
    window = open_window(_settings_with_presets()).window
    find(window, QListWidget, "group_menu").setCurrentRow(2)

    # 検証
    authorization = _preset_field(window, "endpoint", 0, "authorization", QLineEdit)
    assert authorization.echoMode() == QLineEdit.EchoMode.Password
    assert authorization.text() == "Bearer x"
    assert _panel(window, "browser").findChild(QLineEdit, "preset_authorization_0") is None
    assert _panel(window, "endpoint").findChild(QCheckBox, "preset_send_enter_0") is None


def test_add_preset_button_action(open_window: Callable[..., Opened]) -> None:
    """「プリセットを足す」は、そのタブの一覧の末尾に空のプリセット（有効、ブラウザ添付は Enter まで送るがオン）を足し、タイトルの欄へフォーカスを移す。"""
    # 準備
    window = open_window(_settings_with_presets()).window
    find(window, QListWidget, "group_menu").setCurrentRow(1)

    # 実行
    _click(window, "add_preset_button_browser")

    # 検証
    assert _preset_field(window, "browser", 2, "title", QLineEdit).text() == ""
    assert _preset_field(window, "browser", 2, "enabled", QCheckBox).isChecked()
    assert _preset_field(window, "browser", 2, "send_enter", QCheckBox).isChecked()
    assert window.focusWidget() is _preset_field(window, "browser", 2, "title")
    assert not find(window, QLabel, "preset_empty_browser").isVisible()


def test_preset_move_buttons_action(open_window: Callable[..., Opened]) -> None:
    """上へ・下へは、同じタブの中でプリセットを 1 つ動かす。先頭の上へ・末尾の下へは押せない。"""
    # 準備
    window = open_window(_settings_with_presets()).window
    find(window, QListWidget, "group_menu").setCurrentRow(1)
    first_up = _panel(window, "browser").findChild(QAbstractButton, "preset_up_0")
    last_down = _panel(window, "browser").findChild(QAbstractButton, "preset_down_1")
    assert first_up is not None
    assert last_down is not None
    assert not first_up.isEnabled()
    assert not last_down.isEnabled()

    # 実行（ChatGPT の「下へ」）
    _panel(window, "browser").findChild(QAbstractButton, "preset_down_0").click()

    # 検証（ブラウザ添付のタブの中だけが入れ替わる）
    assert [item["title"] for item in window.collect()["presets"]] == ["Claude", "ChatGPT", "受け口"]


def test_preset_remove_button_action(open_window: Callable[..., Opened]) -> None:
    """消すボタンは、プリセットを一覧から消す（保存するまで settings.toml には書かない）。最後の 1 件を消すと案内が出る。"""
    # 準備
    opened = open_window(_settings_with_presets())
    window = opened.window
    find(window, QListWidget, "group_menu").setCurrentRow(2)

    # 実行
    _panel(window, "endpoint").findChild(QAbstractButton, "preset_remove_0").click()

    # 検証
    assert [item["title"] for item in window.collect()["presets"]] == ["ChatGPT", "Claude"]
    assert find(window, QLabel, "preset_empty_endpoint").isVisible()
    opened.deps.save_settings.assert_not_called()


def test_preset_hotkey_field_action(open_window: Callable[..., Opened]) -> None:
    """プリセットのホットキーの欄は、押した組み合わせが入り、保存では pynput の書式で書く。「空にする」で空に戻せる。"""
    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(1)
    _add_preset(window, "browser", "ChatGPT", "https://chatgpt.com")
    edit = _preset_field(window, "browser", 0, "hotkey")
    clear = _panel(window, "browser").findChild(QAbstractButton, "preset_hotkey_clear_0")
    assert clear is not None
    assert not clear.isEnabled()

    # 実行（押す）
    edit.setFocus()
    QTest.keyClick(
        edit,
        Qt.Key.Key_5,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )

    # 検証（押した後）
    assert edit.text() == "Ctrl+Alt+5"
    assert window.collect()["presets"][0]["hotkey"] == "<ctrl>+<alt>+5"
    assert clear.isEnabled()

    # 実行（空にする）
    clear.click()

    # 検証（空にした後）
    assert edit.text() == ""
    assert window.collect()["presets"][0]["hotkey"] == ""


def test_preset_options_fields(open_window: Callable[..., Opened]) -> None:
    """タブのオプションの欄は、その種類のタブにだけ出る。補助文を欄の下に出す。"""
    # 実行
    window = open_window().window

    # 検証
    assert _field(window, "preset_options.browser.open_delay_sec", QLineEdit).text() == "3.0"
    assert _field(window, "preset_options.endpoint.timeout_sec", QLineEdit).text() == "1.5"
    notes = [label.text() for label in window.findChildren(QLabel)]
    assert "貼り付けてから Enter を送るまでの秒数は「出力先」の値を使う。" in notes
    assert (
        "既定は 1.5 秒で、10 秒まで入れられる。この秒数で届かなければ、送り直さずにトレイで知らせる。"
        in notes
    )


def test_save_collects_presets_in_tab_order(open_window: Callable[..., Opened]) -> None:
    """保存では、ブラウザ添付のタブの並び → エンドポイントへ送るのタブの並びの順に 1 つの一覧にして書く。"""
    # 準備
    opened = open_window(_settings_with_presets())
    opened.deps.save_settings.return_value = False

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved = opened.deps.save_settings.call_args.args[0]
    assert [(preset.kind, preset.title) for preset in saved.presets] == [
        ("browser", "ChatGPT"),
        ("browser", "Claude"),
        ("endpoint", "受け口"),
    ]
    assert saved.presets[2].authorization == "Bearer x"
    assert saved.presets[1].send_enter is False


# === pick_glossary_button ===


def test_pick_glossary_button_action(
    open_window: Callable[..., Opened], monkeypatch: pytest.MonkeyPatch
) -> None:
    """「選ぶ…」はファイルを選ぶダイアログ（CSV）を開き、選んだパスを用語集の欄へ入れる。選ばなければ変えない。"""
    # 準備
    window = open_window().window
    find(window, QListWidget, "group_menu").setCurrentRow(5)
    chosen = MagicMock(return_value=("C:/words/yogo.csv", "CSV (*.csv)"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", chosen)

    # 実行
    button = find(window, QPushButton, "pick_glossary_button")
    assert button.text() == "選ぶ…"
    button.click()
    after_choose = _field(window, "glossary_path", QLineEdit).text()
    chosen.return_value = ("", "")
    button.click()

    # 検証
    assert after_choose == "C:/words/yogo.csv"
    assert _field(window, "glossary_path", QLineEdit).text() == "C:/words/yogo.csv"
    assert "csv" in chosen.call_args.args[-1].lower()


def test_pick_glossary_button_when_visible(open_window: Callable[..., Opened]) -> None:
    """「選ぶ…」は文字起こしのまとまりを選んだときだけ出る。"""
    # 準備
    window = open_window().window
    button = find(window, QPushButton, "pick_glossary_button")

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(5)

    # 検証
    assert button.isVisible()


# === restart_notice・save_and_restart_button ===


def test_restart_notice_when_restart_field_changed(open_window: Callable[..., Opened]) -> None:
    """反映が restart の欄を開いたときの値から変えると、件数つきの再起動の知らせと「保存して再起動」を出す。"""
    # 準備
    window = open_window().window
    notice = find(window, QLabel, "restart_notice")
    hidden_at_open = not notice.isVisible()

    # 実行
    _set_text(window, RESTART_KEY, "12")

    # 検証
    assert hidden_at_open
    assert notice.isVisible()
    assert notice.text() == (
        "「再起動で反映」の設定を 1 件変えました。「保存して再起動」で保存すると、すぐに効きます。"
    )
    assert find(window, QPushButton, "save_and_restart_button").isVisible()


def test_restart_notice_when_two_fields_changed(open_window: Callable[..., Opened]) -> None:
    """変えた「再起動で反映」の欄の数を、知らせの件数に出す。"""
    # 準備
    window = open_window().window

    # 実行
    _set_text(window, RESTART_KEY, "12")
    _set_text(window, "transcription.local_whisper.best_of", "7")

    # 検証
    assert "を 2 件変えました" in find(window, QLabel, "restart_notice").text()


def test_restart_notice_when_reverted(open_window: Callable[..., Opened]) -> None:
    """開いたときの値へ戻すと、知らせと「保存して再起動」を隠す。"""
    # 準備
    window = open_window().window
    original = _field(window, RESTART_KEY, QLineEdit).text()
    _set_text(window, RESTART_KEY, "12")

    # 実行
    _set_text(window, RESTART_KEY, original)

    # 検証
    assert not find(window, QLabel, "restart_notice").isVisible()
    assert not find(window, QPushButton, "save_and_restart_button").isVisible()


def test_restart_notice_when_immediate_field_changed(open_window: Callable[..., Opened]) -> None:
    """反映が immediate の欄を変えても、再起動の知らせは出さない。"""
    # 準備
    window = open_window().window

    # 実行
    _set_text(window, IMMEDIATE_KEY, "1.0")

    # 検証
    assert not find(window, QLabel, "restart_notice").isVisible()
    assert not find(window, QPushButton, "save_and_restart_button").isVisible()


def test_save_and_restart_button_action(open_window: Callable[..., Opened]) -> None:
    """「保存して再起動」は確かめて書き、設定画面を閉じて再起動を頼む。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "12")

    # 実行
    _click(opened.window, "save_and_restart_button")

    # 検証
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].transcription.local_whisper.beam_size == 12
    opened.restart_requested.assert_called_once()
    opened.closed.assert_called_once()
    assert not opened.window.isVisible()


def test_save_and_restart_button_when_invalid(open_window: Callable[..., Opened]) -> None:
    """確かめに通らなければ書かず、再起動も頼まず、エラーの一覧を出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "abc")

    # 実行
    _click(opened.window, "save_and_restart_button")

    # 検証
    opened.deps.save_settings.assert_not_called()
    opened.restart_requested.assert_not_called()
    assert opened.window.isVisible()
    assert find(opened.window, QFrame, "error_summary").isVisible()


# === reset_button・reset_dialog・reset_notice・restart_now_button ===


def _settings_with_small_model() -> Settings:
    """文字起こしのモデルを既定から変えた設定（既定に戻すと「再起動で反映」の設定が 1 件変わる）。"""
    from voice_paste.shared.settings import LocalWhisperSettings, Settings, TranscriptionSettings

    return SETTINGS_MODEL(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small"))
    )


def test_reset_dialog_content(open_window: Callable[..., Opened]) -> None:
    """「既定に戻す」を押すと確認を出す。見出し・本文・ボタンの文言が合い、最初のフォーカスと Esc は「設定画面へ戻る」。"""
    # 準備
    opened = open_window()
    seen: dict[str, Any] = {}

    def _inspect(box: QMessageBox) -> None:
        """出た確認の文言とボタンを控える。"""
        seen["name"] = box.objectName()
        seen["title"] = box.windowTitle()
        seen["text"] = box.text()
        seen["body"] = box.informativeText()
        seen["reset"] = find(box, QPushButton, "reset_button").text()
        seen["back"] = find(box, QPushButton, "back_button").text()
        seen["default"] = box.defaultButton() is find(box, QPushButton, "back_button")
        seen["escape"] = box.escapeButton() is find(box, QPushButton, "back_button")

    driver = ModalDriver()
    driver.answer("back_button", _inspect)

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    assert seen == {
        "name": "reset_dialog",
        "title": "voice-paste の設定",
        "text": "全ての設定を既定に戻しますか",
        "body": (
            "出力先・ホットキーを含む全ての設定が既定の値になり、カスタムプリセットは全て消えます。"
            "元に戻せません。"
            "「再起動で反映」の設定は、再起動するまで今の値で動きます。"
        ),
        "reset": "既定に戻す",
        "back": "設定画面へ戻る",
        "default": True,
        "escape": True,
    }


def test_reset_dialog_when_back(open_window: Callable[..., Opened]) -> None:
    """「設定画面へ戻る」はダイアログだけを閉じ、変えた値を残した設定画面へ戻る。書かない。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.75")
    driver = ModalDriver()
    driver.answer("back_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    assert _field(opened.window, IMMEDIATE_KEY, QLineEdit).text() == "1.75"
    opened.deps.save_settings.assert_not_called()
    assert opened.window.isVisible()


def test_reset_dialog_when_reset(open_window: Callable[..., Opened]) -> None:
    """「既定に戻す」は全てのキーを既定の値で書き、設定画面に戻って既定の値を欄に入れる。"""
    from voice_paste.shared.settings import Settings

    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.75")
    driver = ModalDriver()
    driver.answer("reset_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    opened.deps.save_settings.assert_called_once_with(SETTINGS_MODEL())
    assert _field(opened.window, IMMEDIATE_KEY, QLineEdit).text() == "0.5"
    assert opened.window.isVisible()


def test_reset_notice_when_restart_setting_changed(open_window: Callable[..., Opened]) -> None:
    """既定に戻して「再起動で反映」の設定の値が変わったとき、件数つきの知らせと「今すぐ再起動」を出す。"""
    # 準備
    opened = open_window(_settings_with_small_model())
    driver = ModalDriver()
    driver.answer("reset_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    notice = find(opened.window, QLabel, "reset_notice")
    assert notice.isVisible()
    assert notice.text() == (
        "既定に戻して保存しました。「再起動で反映」の設定 1 件は、再起動するまで前の値で動きます。"
    )
    assert find(opened.window, QPushButton, "restart_now_button").isVisible()
    assert find(opened.window, QPushButton, "restart_now_button").text() == "今すぐ再起動"


def test_reset_notice_when_no_restart_setting_changed(open_window: Callable[..., Opened]) -> None:
    """既定に戻しても「再起動で反映」の設定が変わらなければ、知らせを出さない。"""
    # 準備
    opened = open_window()
    driver = ModalDriver()
    driver.answer("reset_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    assert not find(opened.window, QLabel, "reset_notice").isVisible()
    assert not find(opened.window, QPushButton, "restart_now_button").isVisible()


def test_reset_notice_when_field_changed(open_window: Callable[..., Opened]) -> None:
    """欄を変えると、既定に戻した知らせと「今すぐ再起動」を消す。"""
    # 準備
    opened = open_window(_settings_with_small_model())
    driver = ModalDriver()
    driver.answer("reset_button")
    _click(opened.window, "reset_button")
    driver.verify()

    # 実行
    _set_text(opened.window, IMMEDIATE_KEY, "1.0")

    # 検証
    assert not find(opened.window, QLabel, "reset_notice").isVisible()
    assert not find(opened.window, QPushButton, "restart_now_button").isVisible()


def test_restart_now_button_action(open_window: Callable[..., Opened]) -> None:
    """「今すぐ再起動」は設定画面を閉じて再起動を頼む。"""
    # 準備
    opened = open_window(_settings_with_small_model())
    driver = ModalDriver()
    driver.answer("reset_button")
    _click(opened.window, "reset_button")
    driver.verify()

    # 実行
    _click(opened.window, "restart_now_button")

    # 検証
    opened.restart_requested.assert_called_once()
    opened.closed.assert_called_once()
    assert not opened.window.isVisible()


# === cancel_button・discard_dialog ===


def test_cancel_button_when_unchanged(open_window: Callable[..., Opened]) -> None:
    """欄を変えていなければ、確認を出さずに設定画面を閉じる。書かない。"""
    # 準備
    opened = open_window()

    # 実行
    with no_modal():
        _click(opened.window, "cancel_button")

    # 検証
    opened.closed.assert_called_once()
    opened.deps.save_settings.assert_not_called()
    assert not opened.window.isVisible()


def test_discard_dialog_content(open_window: Callable[..., Opened]) -> None:
    """欄を変えたまま「キャンセル」を押すと確認を出す。件数つきの本文で、最初のフォーカスと Esc は「設定画面へ戻る」。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.0")
    _set_text(opened.window, "ui.wave_gain", "3")
    seen: dict[str, Any] = {}

    def _inspect(box: QMessageBox) -> None:
        """出た確認の文言とボタンを控える。"""
        seen["name"] = box.objectName()
        seen["title"] = box.windowTitle()
        seen["text"] = box.text()
        seen["body"] = box.informativeText()
        seen["discard"] = find(box, QPushButton, "discard_button").text()
        seen["back"] = find(box, QPushButton, "back_button").text()
        seen["default"] = box.defaultButton() is find(box, QPushButton, "back_button")
        seen["escape"] = box.escapeButton() is find(box, QPushButton, "back_button")

    driver = ModalDriver()
    driver.answer("back_button", _inspect)

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    assert seen == {
        "name": "discard_dialog",
        "title": "voice-paste の設定",
        "text": "変えた値を捨てて閉じますか",
        "body": "保存していない変更が 2 件あります。閉じると、変えた値は保存されません。",
        "discard": "捨てて閉じる",
        "back": "設定画面へ戻る",
        "default": True,
        "escape": True,
    }


def test_discard_dialog_when_discard(open_window: Callable[..., Opened]) -> None:
    """「捨てて閉じる」はダイアログと設定画面を閉じる。settings.toml は書かない。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.0")
    driver = ModalDriver()
    driver.answer("discard_button")

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    opened.closed.assert_called_once()
    opened.deps.save_settings.assert_not_called()
    assert not opened.window.isVisible()


def test_discard_dialog_when_back(open_window: Callable[..., Opened]) -> None:
    """「設定画面へ戻る」はダイアログだけを閉じ、変えた値を残した設定画面へ戻る。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.0")
    driver = ModalDriver()
    driver.answer("back_button")

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    opened.closed.assert_not_called()
    assert opened.window.isVisible()
    assert _field(opened.window, IMMEDIATE_KEY, QLineEdit).text() == "1.0"


def test_discard_dialog_when_escape_in_dialog(open_window: Callable[..., Opened]) -> None:
    """確認の Esc は「設定画面へ戻る」と同じで、設定画面は開いたまま。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.0")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    QTimer.singleShot(0, lambda: QTest.keyClick(QApplication.activeModalWidget(), Qt.Key.Key_Escape))

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    opened.closed.assert_not_called()
    assert opened.window.isVisible()


@pytest.mark.parametrize("route", ["escape_key", "window_close"])
def test_discard_dialog_when_closed_by(open_window: Callable[..., Opened], route: str) -> None:
    """Esc・窓の閉じるも「キャンセル」と同じ（変えていなければ閉じ、変えていれば確認を出す）。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.0")
    driver = ModalDriver()
    driver.answer("back_button")

    # 実行
    if route == "escape_key":
        QTest.keyClick(opened.window, Qt.Key.Key_Escape)
    else:
        opened.window.close()

    # 検証
    driver.verify()
    assert opened.window.isVisible()


def test_discard_dialog_when_unchanged_by_window_close(open_window: Callable[..., Opened]) -> None:
    """変えていなければ、窓の閉じるで確認を出さずに閉じる。"""
    # 準備
    opened = open_window()

    # 実行
    with no_modal():
        opened.window.close()

    # 検証
    opened.closed.assert_called_once()


# === enter_modifiers ===


def test_enter_modifiers_when_visible(open_window: Callable[..., Opened]) -> None:
    """「出力先」のまとまりに、欄の名前「Enter と一緒に押す修飾キー」と、その下の行に「Ctrl」「Alt」「Shift」のチェックボックスを横に並べる。"""
    # 実行
    window = open_window().window

    # 検証
    name_label = _label_with_text(window, "Enter と一緒に押す修飾キー")
    boxes = [_field(window, f"outputs[0].enter_modifiers_{value}", QCheckBox) for value in ("ctrl", "alt", "shift")]
    assert name_label.isVisible()
    assert [box.text() for box in boxes] == ["Ctrl", "Alt", "Shift"]
    assert all(box.isVisible() for box in boxes)
    # 名前の下の行に、同じ高さで左から Ctrl・Alt・Shift の順に並ぶ
    assert all(_top_of(box, window) >= _top_of(name_label, window) + name_label.height() for box in boxes)
    assert len({_top_of(box, window) for box in boxes}) == 1
    assert _left_of(boxes[0], window) < _left_of(boxes[1], window) < _left_of(boxes[2], window)


def test_enter_modifiers_when_initial_value(open_window: Callable[..., Opened]) -> None:
    """開いたときの settings.toml の修飾キーだけをオンにして開く（既定は全てオフ）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 準備
    settings = SETTINGS_MODEL(
        outputs=[PasteAndSendSettings(enter_modifiers=["alt"]), PasteOnlySettings(), CopyOnlySettings()]
    )

    # 実行
    default_window = open_window().window
    window = open_window(settings).window

    # 検証
    values = ("ctrl", "alt", "shift")
    assert [_field(default_window, f"outputs[0].enter_modifiers_{v}", QCheckBox).isChecked() for v in values] == [
        False,
        False,
        False,
    ]
    assert [_field(window, f"outputs[0].enter_modifiers_{v}", QCheckBox).isChecked() for v in values] == [
        False,
        True,
        False,
    ]


# === field_ui.theme ===

THEME_GROUP_ROW = 6
"""まとまりのメニューの「画面」の行。"""


@pytest.mark.parametrize(
    ("theme", "checked"),
    [
        pytest.param("system", "Windows の設定に従う", id="system"),
        pytest.param("light", "ライト", id="light"),
        pytest.param("dark", "ダーク", id="dark"),
    ],
)
def test_ui_theme_field_initial_value(
    open_window: Callable[..., Opened], theme: str, checked: str
) -> None:
    """「画面」のまとまりの先頭に「画面の明暗」があり、今の ui.theme のボタンが選ばれている。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    window = open_window(SETTINGS_MODEL(ui=UiSettings(theme=theme))).window

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(THEME_GROUP_ROW)

    # 検証
    field = _field(window, "ui.theme")
    buttons = field.findChildren(QRadioButton)
    assert [button.text() for button in buttons] == ["Windows の設定に従う", "ライト", "ダーク"]
    assert [button.text() for button in buttons if button.isChecked()] == [checked]
    assert _label_with_text(window, "画面の明暗").isVisible()
    assert _top_of(field, window) < _top_of(_field(window, "ui.topmost"), window)
    assert window.findChild(QLabel, "restart_badge_ui.theme") is None


def test_ui_theme_field_action(
    make_ui: Callable[..., Ui], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """別の値を選んで保存すると settings.toml の ui.theme が書き換わり、再起動せずに明暗を当て直す（再起動の印は出ない）。"""
    from functools import partial

    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings

    # 準備: 本物の保存（settings.toml へ書く）につなぎ、ui.theme=system で設定画面を開く
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file, SETTINGS_MODEL))
    apply_theme = MagicMock(return_value=None)
    ui = make_ui(
        store.get(),
        get_settings=store.get,
        save_settings=partial(
            apply_settings,
            settings_file=settings_file,
            store=store,
            check_hotkeys=lambda _hotkeys: None,
        ),
        apply_theme=apply_theme,
    )
    ui.controller.open_settings()
    window = ui.controller._settings_window
    find(window, QListWidget, "group_menu").setCurrentRow(THEME_GROUP_ROW)
    light = next(
        button for button in _field(window, "ui.theme").findChildren(QRadioButton)
        if button.text() == "ライト"
    )

    # 実行
    light.click()
    assert not find(window, QLabel, "restart_notice").isVisible()
    _click(window, "save_button")

    # 検証
    assert load_settings(settings_file, SETTINGS_MODEL).ui.theme == "light"
    assert 'theme = "light"' in settings_file.read_text(encoding="utf-8")
    apply_theme.assert_called_once_with()
    assert not window.isVisible()


# === save_button ===


def test_save_button_action(open_window: Callable[..., Opened]) -> None:
    """「保存」は確かめて書き、設定画面を閉じる。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].recording.fade_sec == 1.25
    opened.saved.assert_called_once()
    opened.closed.assert_called_once()
    assert not opened.window.isVisible()


def test_save_button_when_enter_modifiers(open_window: Callable[..., Opened]) -> None:
    """オンにした修飾キーを、列挙の並び（Ctrl・Alt・Shift）で settings.toml の enter_modifiers に書く。"""
    # 準備（Shift → Ctrl の順にオンにする）
    opened = open_window()
    _field(opened.window, "outputs[0].enter_modifiers_shift", QCheckBox).setChecked(True)
    _field(opened.window, "outputs[0].enter_modifiers_ctrl", QCheckBox).setChecked(True)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].outputs[0].enter_modifiers == ["ctrl", "shift"]
    opened.saved.assert_called_once()


def test_save_button_when_default(open_window: Callable[..., Opened]) -> None:
    """既定のままでも保存できる（録音の開始と「貼り付けて送信」が同じホットキーなのは重なりにしない）。"""
    from voice_paste.shared.settings import Settings

    # 準備
    opened = open_window()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_called_once_with(SETTINGS_MODEL())


def test_save_button_when_invalid(open_window: Callable[..., Opened]) -> None:
    """確かめに通らなければ書かず、エラーの一覧と欄の下のエラーを出し、入れた値は消さない。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "abc")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_not_called()
    opened.closed.assert_not_called()
    assert opened.window.isVisible()
    assert _field(opened.window, IMMEDIATE_KEY, QLineEdit).text() == "abc"


# === error_summary ===


def test_error_summary_when_editing(open_window: Callable[..., Opened]) -> None:
    """入力の途中では、エラーの一覧を出さない（保存を押したときだけ）。"""
    # 実行
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "abc")

    # 検証
    assert not find(opened.window, QFrame, "error_summary").isVisible()


def test_error_summary_when_invalid(open_window: Callable[..., Opened]) -> None:
    """確かめに通らない欄があれば、件数つきの見出しと欄ごとのエラーを並べ、フォーカスを一覧へ移す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "abc")
    _set_text(opened.window, "ui.wave_gain", "x")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    summary = find(opened.window, QFrame, "error_summary")
    assert summary.isVisible()
    rows = _error_rows(opened.window)
    assert rows[0] == "保存できませんでした。2 件の欄を直してください。"
    assert len(rows) == 3
    assert opened.window.focusWidget() is summary


def test_error_summary_row_action(open_window: Callable[..., Opened]) -> None:
    """一覧の各行はその欄へのリンクで、押すとその欄のまとまりへ切り替えて欄へフォーカスを移す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "abc")
    _click(opened.window, "save_button")
    find(opened.window, QListWidget, "group_menu").setCurrentRow(8)
    link = next(
        label for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "href" in label.text()
    )

    # 実行
    link.linkActivated.emit(IMMEDIATE_KEY)

    # 検証
    assert find(opened.window, QListWidget, "group_menu").currentRow() == 4
    assert opened.window.focusWidget() is _field(opened.window, IMMEDIATE_KEY)


# === input_checks ===


def test_input_check_when_not_number(open_window: Callable[..., Opened]) -> None:
    """数値の欄に数値でない文字: 「数値を入れてください（例: {既定の値}）。」をその欄の下とエラーの一覧に出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, "outputs[0].enter_delay_sec", "abc")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "数値を入れてください（例: 0.5）。"
    assert find(opened.window, QLabel, "error_outputs[0].enter_delay_sec").text() == message
    assert find(opened.window, QLabel, "error_outputs[0].enter_delay_sec").isVisible()
    assert any(row.endswith(f": {message}") for row in _error_rows(opened.window))


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("api.port", "80", "1024〜65535 の値を入れてください。"),
        ("api.port", "70000", "1024〜65535 の値を入れてください。"),
        ("history.retention_days", "0", "1 以上の値を入れてください。"),
        ("recording.fade_sec", "-1", "0 以上の値を入れてください。"),
    ],
)
def test_input_check_when_out_of_range(
    open_window: Callable[..., Opened], key: str, value: str, message: str
) -> None:
    """範囲の外の数値: 「{最小}〜{最大} の値を入れてください。」（上限が無ければ「{最小} 以上の値を入れてください。」）を出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, key, value)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert find(opened.window, QLabel, f"error_{key}").text() == message
    assert any(row.endswith(f": {message}") for row in _error_rows(opened.window))


def test_input_check_when_hotkey_overlap(open_window: Callable[..., Opened]) -> None:
    """ほかのホットキーの欄と同じ組み合わせ: 「「{重なった欄の名前}」と同じホットキーです。別のキーにしてください。」を出す。"""
    # 準備
    opened = open_window()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(3)
    _press(
        opened.window,
        "hotkeys.cancel",
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "「録音を一時停止・再開する」と同じホットキーです。別のキーにしてください。"
    assert find(opened.window, QLabel, "error_hotkeys.cancel").text() == message
    assert any(row.endswith(f": {message}") for row in _error_rows(opened.window))
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_preset_title_empty(open_window: Callable[..., Opened]) -> None:
    """プリセットのタイトルが空: 「タイトルを入れてください。」をその欄の下とエラーの一覧に出す。"""
    # 準備
    opened = open_window()
    _add_preset(opened.window, "browser", "", "https://chatgpt.com")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "タイトルを入れてください。"
    assert _field_errors(opened.window) == [message]
    assert any(
        row == f"プリセット 1 件目のタイトル: {message}" for row in _error_rows(opened.window)
    )
    opened.deps.save_settings.assert_not_called()


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("", "URL を入れてください（例: https://example.com/hook）。"),
        ("gemini.google.com", "http:// か https:// で始まる URL を入れてください。"),
    ],
    ids=["empty", "no_scheme"],
)
def test_input_check_when_preset_url_invalid(
    open_window: Callable[..., Opened], url: str, message: str
) -> None:
    """プリセットの URL が空・http:// か https:// で始まらない: それぞれの文言をその欄の下とエラーの一覧に出す。"""
    # 準備
    opened = open_window()
    _add_preset(opened.window, "endpoint", "受け口", url)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _field_errors(opened.window) == [message]
    assert any(row.endswith(f": {message}") for row in _error_rows(opened.window))


def test_input_check_when_preset_hotkey_overlap(open_window: Callable[..., Opened]) -> None:
    """プリセットのホットキーが、ほかのプリセットと同じ: 「プリセット「{タイトル}」と同じキーです。別のキーにしてください。」を出す。種類をまたぐときは種類も添える。"""
    # 準備
    opened = open_window()
    for kind, title in (("browser", "ChatGPT"), ("endpoint", "受け口")):
        _add_preset(opened.window, kind, title, "https://example.com")
        edit = _preset_field(opened.window, kind, 0, "hotkey")
        edit.setFocus()
        QTest.keyClick(
            edit, Qt.Key.Key_5, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        )

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "「ブラウザ添付」のプリセット「ChatGPT」と同じキーです。別のキーにしてください。"
    assert _field_errors(opened.window) == [message]
    assert any(row.endswith(f": {message}") for row in _error_rows(opened.window))
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_timeout_out_of_range(open_window: Callable[..., Opened]) -> None:
    """エンドポイントへ送るのタイムアウトが 0.5〜10 の外: 「0.5〜10 の値を入れてください。」を出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, "preset_options.endpoint.timeout_sec", "11")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "0.5〜10 の値を入れてください。"
    assert find(opened.window, QLabel, "error_preset_options.endpoint.timeout_sec").text() == message
    assert any(row.endswith(f": {message}") for row in _error_rows(opened.window))


def test_error_summary_row_action_when_preset(open_window: Callable[..., Opened]) -> None:
    """プリセットの欄の行を押すと、その種類のタブへ切り替えて欄へフォーカスを移す。"""
    # 準備
    opened = open_window()
    _add_preset(opened.window, "endpoint", "受け口", "")
    _click(opened.window, "save_button")
    find(opened.window, QListWidget, "group_menu").setCurrentRow(8)
    link = next(
        label for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "href" in label.text()
    )

    # 実行
    link.linkActivated.emit("presets[0].url")

    # 検証
    assert find(opened.window, QListWidget, "group_menu").currentRow() == 2
    assert opened.window.focusWidget() is _preset_field(opened.window, "endpoint", 0, "url")


def test_input_check_when_hotkey_unreadable(open_window: Callable[..., Opened]) -> None:
    """pynput が読めない組み合わせ: 「ホットキーを受け付けられませんでした（{理由}）。別のキーにしてください。」をエラーの一覧に出す。"""
    from voice_paste.shared.errors import HotkeyError

    # 準備
    opened = open_window()
    opened.deps.save_settings.side_effect = HotkeyError("<ctrl>+<nokey> を読めません")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    rows = _error_rows(opened.window)
    assert "ホットキーを受け付けられませんでした（<ctrl>+<nokey> を読めません）。別のキーにしてください。" in rows
    assert _field_errors(opened.window) == []
    assert opened.window.isVisible()
    opened.closed.assert_not_called()


@pytest.mark.parametrize("button", ["save_button", "save_and_restart_button"])
def test_input_check_trigger(open_window: Callable[..., Opened], button: str) -> None:
    """検証は保存・保存して再起動のボタンのクリックで行う。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "abc")
    _set_text(opened.window, "api.port", "80")

    # 実行
    _click(opened.window, button)

    # 検証
    assert len(_field_errors(opened.window)) == 2
    opened.deps.save_settings.assert_not_called()


# === 設定画面を開いている間はホットキーを止める ===


@pytest.mark.parametrize("route", ["save", "cancel", "window_close"])
def test_settings_window_suspends_hotkeys(make_ui: Callable[..., Ui], route: str) -> None:
    """開いている間はホットキーの受付を止め（欄で押したキーで録音や確定が動かない）、どの経路で閉じても今の設定で張り直す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.open_settings()
    window = ui.controller._settings_window
    suspended_while_open = ui.deps.suspend_hotkeys.call_count
    resumed_while_open = ui.deps.resume_hotkeys.call_count
    if route == "save":
        _click(window, "save_button")
    elif route == "cancel":
        _click(window, "cancel_button")
    else:
        window.close()

    # 検証
    assert suspended_while_open == 1
    assert resumed_while_open == 0
    ui.deps.suspend_hotkeys.assert_called_once()
    ui.deps.resume_hotkeys.assert_called_once()
    assert ui.controller._settings_window is None


def test_settings_window_when_opened_twice(make_ui: Callable[..., Ui]) -> None:
    """開いていれば、新しく開かず前面に出すだけにする（ホットキーを止めるのも 1 回）。"""
    # 準備
    ui = make_ui()
    ui.controller.open_settings()
    window = ui.controller._settings_window

    # 実行
    ui.controller.open_settings()

    # 検証
    assert ui.controller._settings_window is window
    assert window.isVisible()
    ui.deps.suspend_hotkeys.assert_called_once()
    window.try_close()
