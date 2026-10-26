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

from tests.integration.ui.helpers import (
    COLOR_TOLERANCE,
    ModalDriver,
    Ui,
    color_distance,
    contrast_ratio,
    count_closer,
    count_near,
    crop_logical,
    dispose_windows_since,
    find,
    indicator_image,
    make_ui_deps,
    no_modal,
    top_level_windows,
)
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
    """設定（無ければ既定）で設定画面を開く関数を返す。テストの後に、開いた窓とダイアログを破棄する。"""
    from voice_paste.ui.windows.settings_window import SettingsWindow

    before = top_level_windows()

    def _open(settings: Settings | None = None, **deps_overrides: object) -> Opened:
        """設定画面を開き、窓の Signal を Mock につなぐ。"""
        deps = make_ui_deps(tmp_path, settings=settings, **deps_overrides)
        window = SettingsWindow(deps)
        opened = Opened(window, deps, MagicMock(), MagicMock(), MagicMock())
        window.closed.connect(opened.closed)
        window.saved.connect(opened.saved)
        window.restart_requested.connect(opened.restart_requested)
        window.show()
        return opened

    yield _open
    dispose_windows_since(before)


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


LIST_KEYS = (
    "outputs",
    "presets",
    "glossaries",
    "glossary_path",
    "active_glossary",
    "glossary_presets",
    "active_glossary_preset",
    "hint_presets",
    "edge_phrases",
)
"""欄ではなく、一覧の部品（出力先・プリセット・用語集・用語集のプリセット・表記のヒント・文頭・文末から消す文言）が持つキー。glossary_path は欄を持たず、glossaries が空のときだけ読む。active_glossary は glossary_presets が空のときだけ読む。"""


def _leaf_keys(settings: Settings) -> list[str]:
    """設定のキー（LIST_KEYS は除く）を、ドット区切りで全て並べる。"""
    from pydantic import BaseModel

    keys: list[str] = []

    def _walk(model: BaseModel, prefix: str) -> None:
        """入れ子のモデルを辿り、末端の項目のキーを集める。"""
        for name in type(model).model_fields:
            value = getattr(model, name)
            key = f"{prefix}{name}"
            if isinstance(value, BaseModel):
                _walk(value, f"{key}.")
            elif name not in LIST_KEYS:
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
    """まとまりのメニューは、出力先・ブラウザ添付・エンドポイントへ送る・ホットキー・録音・文字起こし・表記のヒント・用語集・ハルシネーション・画面・履歴とログ・API の順で、既定は出力先。"""
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
        "表記のヒント",
        "用語集",
        "ハルシネーション",
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
        (9, "ui.wave_gain", "transcription.local_whisper.model"),
        (10, "history.retention_days", "ui.wave_gain"),
        (11, "api.port", "history.retention_days"),
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
    menu.setCurrentRow(10)
    menu.setCurrentRow(4)

    # 検証
    assert _field(window, IMMEDIATE_KEY, QLineEdit).text() == "1.25"


# === field_{key}・restart_badge_{key} ===


def test_field_for_every_setting_key(open_window: Callable[..., Opened]) -> None:
    """settings.toml の全てのキーに欄がある（項目を足しても画面の直しが増えない。出力先・プリセット・用語集は、それぞれのまとまりの一覧が持つ）。"""
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
    find(window, QListWidget, "group_menu").setCurrentRow(10)
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
    opened.deps.save_settings.assert_called_once_with(SETTINGS_MODEL(), {})
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

THEME_GROUP_ROW = 9
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
            save_glossary=MagicMock(),
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
    assert window.isVisible()
    assert find(window, QLabel, "saved_notice").text() == "保存しました。"


# === field_ui.show_hotkeys ===

SHOW_HOTKEYS_LABEL = "録音の画面のボタンにホットキーを出すか"
"""ui.show_hotkeys の欄の名前（設定の設計書の title）。"""

TRANSCRIBING_SHOW_HOTKEYS_LABEL = "文字起こし中の表示のボタンにホットキーを出すか"
"""ui.transcribing_show_hotkeys の欄の名前（設定の設計書の title）。"""


@pytest.mark.parametrize("show_hotkeys", [True, False], ids=["on", "off"])
def test_ui_show_hotkeys_field_initial_value(
    open_window: Callable[..., Opened], show_hotkeys: bool
) -> None:
    """「画面」のまとまりの末尾に、欄の名前が「録音の画面のボタンにホットキーを出すか」のチェックボックスがあり、今の ui.show_hotkeys の値になっている（再起動の印は出ない）。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    window = open_window(SETTINGS_MODEL(ui=UiSettings(show_hotkeys=show_hotkeys))).window

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(THEME_GROUP_ROW)

    # 検証
    field = _field(window, "ui.show_hotkeys", QCheckBox)
    assert field.isChecked() == show_hotkeys
    assert _label_with_text(window, SHOW_HOTKEYS_LABEL).isVisible()
    assert _top_of(field, window) > _top_of(_field(window, "ui.wave_gain"), window)
    assert window.findChild(QLabel, "restart_badge_ui.show_hotkeys") is None


def test_ui_show_hotkeys_field_action(
    make_ui: Callable[..., Ui], tmp_path: Path
) -> None:
    """チェックを外して保存すると settings.toml の ui.show_hotkeys が false に書き換わり、再起動せずに効く（再起動の印は出ない）。"""
    from functools import partial

    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings

    # 準備: 本物の保存（settings.toml へ書く）につなぎ、既定（ui.show_hotkeys=true）で設定画面を開く
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file, SETTINGS_MODEL))
    ui = make_ui(
        store.get(),
        get_settings=store.get,
        save_settings=partial(
            apply_settings,
            settings_file=settings_file,
            store=store,
            check_hotkeys=lambda _hotkeys: None,
            save_glossary=MagicMock(),
        ),
    )
    ui.controller.open_settings()
    window = ui.controller._settings_window
    find(window, QListWidget, "group_menu").setCurrentRow(THEME_GROUP_ROW)

    # 実行
    _field(window, "ui.show_hotkeys", QCheckBox).setChecked(False)
    assert not find(window, QLabel, "restart_notice").isVisible()
    _click(window, "save_button")

    # 検証
    saved = load_settings(settings_file, SETTINGS_MODEL)
    assert not saved.ui.show_hotkeys
    assert saved.ui.transcribing_show_hotkeys
    assert "show_hotkeys = false" in settings_file.read_text(encoding="utf-8").splitlines()
    assert not store.get().ui.show_hotkeys
    assert store.get().ui.transcribing_show_hotkeys
    assert window.isVisible()
    assert find(window, QLabel, "saved_notice").text() == "保存しました。"


@pytest.mark.parametrize("transcribing_show_hotkeys", [True, False], ids=["on", "off"])
def test_ui_transcribing_show_hotkeys_field_initial_value(
    open_window: Callable[..., Opened], transcribing_show_hotkeys: bool
) -> None:
    """「画面」のまとまりの末尾の ui.show_hotkeys の次に、欄の名前が「文字起こし中の表示のボタンにホットキーを出すか」のチェックボックスがあり、今の ui.transcribing_show_hotkeys の値になっている（再起動の印は出ない）。"""
    from voice_paste.shared.settings import UiSettings

    # 準備: 録音の画面の値とは逆にして、欄が自分のキーの値を出すことを確かめる
    window = open_window(
        SETTINGS_MODEL(
            ui=UiSettings(
                show_hotkeys=not transcribing_show_hotkeys,
                transcribing_show_hotkeys=transcribing_show_hotkeys,
            )
        )
    ).window

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(THEME_GROUP_ROW)

    # 検証
    field = _field(window, "ui.transcribing_show_hotkeys", QCheckBox)
    assert field.isChecked() == transcribing_show_hotkeys
    assert _label_with_text(window, TRANSCRIBING_SHOW_HOTKEYS_LABEL).isVisible()
    assert _top_of(field, window) > _top_of(_field(window, "ui.show_hotkeys"), window)
    assert window.findChild(QLabel, "restart_badge_ui.transcribing_show_hotkeys") is None


def test_ui_transcribing_show_hotkeys_field_action(
    make_ui: Callable[..., Ui], tmp_path: Path
) -> None:
    """チェックを外して保存すると settings.toml の ui.transcribing_show_hotkeys だけが false に書き換わり、再起動せずに効く（再起動の印は出ない）。"""
    from functools import partial

    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings

    # 準備: 本物の保存（settings.toml へ書く）につなぎ、既定（どちらも true）で設定画面を開く
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file, SETTINGS_MODEL))
    ui = make_ui(
        store.get(),
        get_settings=store.get,
        save_settings=partial(
            apply_settings,
            settings_file=settings_file,
            store=store,
            check_hotkeys=lambda _hotkeys: None,
            save_glossary=MagicMock(),
        ),
    )
    ui.controller.open_settings()
    window = ui.controller._settings_window
    find(window, QListWidget, "group_menu").setCurrentRow(THEME_GROUP_ROW)

    # 実行
    _field(window, "ui.transcribing_show_hotkeys", QCheckBox).setChecked(False)
    assert not find(window, QLabel, "restart_notice").isVisible()
    _click(window, "save_button")

    # 検証
    saved = load_settings(settings_file, SETTINGS_MODEL)
    assert not saved.ui.transcribing_show_hotkeys
    assert saved.ui.show_hotkeys
    assert "transcribing_show_hotkeys = false" in settings_file.read_text(encoding="utf-8")
    assert not store.get().ui.transcribing_show_hotkeys
    assert store.get().ui.show_hotkeys
    assert window.isVisible()
    assert find(window, QLabel, "saved_notice").text() == "保存しました。"


# === save_button ===


def test_save_button_action(open_window: Callable[..., Opened]) -> None:
    """「保存」は確かめて書き、設定画面を開いたまま保存した知らせを出す。入れた値は保つ。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].recording.fade_sec == 1.25
    opened.saved.assert_called_once()
    opened.closed.assert_not_called()
    assert opened.window.isVisible()
    assert _field(opened.window, IMMEDIATE_KEY, QLineEdit).text() == "1.25"
    assert find(opened.window, QLabel, "saved_notice").text() == "保存しました。"


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


def test_save_button_when_default(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """既定のままでも保存できる（録音の開始と「貼り付けて送信」が同じホットキーなのは重なりにしない。用語集は今の 1 件を一覧に書き、「既定」のプリセットがそれだけを使う形に書く。書き戻す CSV は無い）。"""
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings

    # 準備
    opened = open_window()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    expected = SETTINGS_MODEL(
        glossaries=[GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")],
        glossary_presets=[GlossaryPresetSettings(name="既定", glossaries=["yogo"])],
        active_glossary_preset="既定",
    )
    opened.deps.save_settings.assert_called_once_with(expected, {})


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


def test_save_button_when_fixed_after_invalid(open_window: Callable[..., Opened]) -> None:
    """直して保存し直すと、前の保存で出したエラーの一覧と欄の下のエラーを消し、保存した知らせを出す。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    # 準備（確かめに通らない値で保存して、エラーの一覧と欄の下のエラーを出しておく）
    opened = open_window()
    _set_text(opened.window, "outputs[0].enter_delay_sec", "abc")
    _click(opened.window, "save_button")
    assert find(opened.window, QFrame, "error_summary").isVisible()
    assert _field_errors(opened.window) == ["数値を入れてください（例: 0.5）。"]

    # 実行
    _set_text(opened.window, "outputs[0].enter_delay_sec", "0.5")
    _click(opened.window, "save_button")
    # エラーの一覧の行は deleteLater で消えるため、削除を済ませてから確かめる
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    # 検証
    opened.deps.save_settings.assert_called_once()
    assert not find(opened.window, QFrame, "error_summary").isVisible()
    assert _error_rows(opened.window) == []
    assert not find(opened.window, QLabel, "error_outputs[0].enter_delay_sec").isVisible()
    assert find(opened.window, QLabel, "error_outputs[0].enter_delay_sec").text() == ""
    assert _field_errors(opened.window) == []
    assert find(opened.window, QLabel, "saved_notice").isVisible()
    assert find(opened.window, QLabel, "saved_notice").text() == "保存しました。"


# === saved_notice・restart_now_button・cancel_button（保存の後） ===

SAVED_TEXT = "保存しました。"
"""ホットキーも「再起動で反映」の欄も変えていない保存の知らせ。"""

HOTKEY_NOTE = "新しいホットキーは、設定画面を閉じると効きます。"
"""ホットキーの欄を変えた保存の知らせに続く文。"""

HOTKEY_GROUP_ROW = 3
"""まとまりのメニューで「ホットキー」の行。"""

CTRL_ALT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier


def _saved_notice(window: QWidget) -> QLabel:
    """保存した知らせ（`saved_notice`）を引く。"""
    return find(window, QLabel, "saved_notice")


def test_saved_notice_when_saved(open_window: Callable[..., Opened]) -> None:
    """ホットキーも「再起動で反映」の欄も変えていない保存では、「保存しました。」だけを出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")
    hidden_at_open = not _saved_notice(opened.window).isVisible()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert hidden_at_open
    assert _saved_notice(opened.window).isVisible()
    assert _saved_notice(opened.window).text() == SAVED_TEXT
    assert not find(opened.window, QPushButton, "restart_now_button").isVisible()
    assert not find(opened.window, QLabel, "restart_notice").isVisible()


@pytest.mark.parametrize(
    ("row", "key"),
    [
        pytest.param(HOTKEY_GROUP_ROW, "hotkeys.start", id="recording_hotkey"),
        pytest.param(0, "outputs[0].hotkey", id="output_hotkey"),
    ],
)
def test_saved_notice_when_hotkey_changed(
    open_window: Callable[..., Opened], row: int, key: str
) -> None:
    """録音のホットキーか出力先の確定のホットキーを変えた保存では、閉じると効くことを添える。"""
    # 準備
    opened = open_window()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(row)
    _press(opened.window, key, Qt.Key.Key_9, CTRL_ALT)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _saved_notice(opened.window).text() == SAVED_TEXT + HOTKEY_NOTE
    assert not find(opened.window, QPushButton, "restart_now_button").isVisible()


def test_saved_notice_when_paste_key_changed(open_window: Callable[..., Opened]) -> None:
    """貼り付けに送るキーだけを変えた保存では、閉じると効くことを添えない。"""
    # 準備
    opened = open_window()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(HOTKEY_GROUP_ROW)
    _press(opened.window, "keyboard.paste_key", Qt.Key.Key_9, CTRL_ALT)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _saved_notice(opened.window).text() == SAVED_TEXT


def test_saved_notice_when_restart_field_changed(open_window: Callable[..., Opened]) -> None:
    """「再起動で反映」の欄を変えた保存では、件数と再起動するまで前の値で動くことを出し、「今すぐ再起動」を右に出す。再起動の知らせと「保存して再起動」は隠す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "12")
    restart_notice_at_edit = find(opened.window, QLabel, "restart_notice").isVisible()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert restart_notice_at_edit
    assert _saved_notice(opened.window).text() == (
        SAVED_TEXT + "「再起動で反映」の設定 1 件は、再起動するまで前の値で動きます。"
    )
    assert find(opened.window, QPushButton, "restart_now_button").isVisible()
    assert find(opened.window, QPushButton, "restart_now_button").text() == "今すぐ再起動"
    assert not find(opened.window, QLabel, "restart_notice").isVisible()
    assert not find(opened.window, QPushButton, "save_and_restart_button").isVisible()


def test_saved_notice_when_hotkey_and_restart_field_changed(
    open_window: Callable[..., Opened],
) -> None:
    """ホットキーと「再起動で反映」の欄をどちらも変えた保存では、ホットキーの文、再起動の文の順に続ける。"""
    # 準備
    opened = open_window()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(HOTKEY_GROUP_ROW)
    _press(opened.window, "hotkeys.start", Qt.Key.Key_9, CTRL_ALT)
    _set_text(opened.window, RESTART_KEY, "12")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _saved_notice(opened.window).text() == (
        SAVED_TEXT
        + HOTKEY_NOTE
        + "「再起動で反映」の設定 1 件は、再起動するまで前の値で動きます。"
    )
    assert find(opened.window, QPushButton, "restart_now_button").isVisible()


def test_saved_notice_when_saved_twice(open_window: Callable[..., Opened]) -> None:
    """続けて 2 回保存しても、「再起動で反映」の件数は開いたときの値から数える。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "12")
    _click(opened.window, "save_button")
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert opened.deps.save_settings.call_count == 2
    assert _saved_notice(opened.window).text() == (
        SAVED_TEXT + "「再起動で反映」の設定 1 件は、再起動するまで前の値で動きます。"
    )


def test_saved_notice_when_field_changed(open_window: Callable[..., Opened]) -> None:
    """保存の後に欄を変えると、保存した知らせと「今すぐ再起動」を消し、再起動の知らせと「保存して再起動」を開いたときの値から数え直して出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "12")
    _click(opened.window, "save_button")

    # 実行
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")

    # 検証
    assert not _saved_notice(opened.window).isVisible()
    assert not find(opened.window, QPushButton, "restart_now_button").isVisible()
    assert find(opened.window, QLabel, "restart_notice").isVisible()
    assert "を 1 件変えました" in find(opened.window, QLabel, "restart_notice").text()
    assert find(opened.window, QPushButton, "save_and_restart_button").isVisible()


def test_restart_now_button_when_saved(open_window: Callable[..., Opened]) -> None:
    """「再起動で反映」の欄を保存した後の「今すぐ再起動」は、設定画面を閉じて再起動を頼む。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, RESTART_KEY, "12")
    _click(opened.window, "save_button")

    # 実行
    _click(opened.window, "restart_now_button")

    # 検証
    opened.restart_requested.assert_called_once()
    opened.closed.assert_called_once()
    assert not opened.window.isVisible()


def test_cancel_button_when_saved(open_window: Callable[..., Opened]) -> None:
    """保存の後に欄を変えずに「キャンセル」を押すと、確認を出さずに設定画面を閉じる。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")
    _click(opened.window, "save_button")

    # 実行
    with no_modal():
        _click(opened.window, "cancel_button")

    # 検証
    opened.closed.assert_called_once()
    opened.deps.save_settings.assert_called_once()
    assert not opened.window.isVisible()


def test_cancel_button_when_changed_after_save(open_window: Callable[..., Opened]) -> None:
    """保存の後に欄を変えて「キャンセル」を押すと、保存した値から変えた件数で確認を出す。"""
    # 準備
    opened = open_window()
    _set_text(opened.window, IMMEDIATE_KEY, "1.25")
    _click(opened.window, "save_button")
    _set_text(opened.window, "ui.wave_gain", "3")
    seen: dict[str, str] = {}

    def _inspect(box: QMessageBox) -> None:
        """出た確認の本文を控える。"""
        seen["body"] = box.informativeText()

    driver = ModalDriver()
    driver.answer("discard_button", _inspect)

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    assert seen["body"] == "保存していない変更が 1 件あります。閉じると、変えた値は保存されません。"
    opened.closed.assert_called_once()
    opened.deps.save_settings.assert_called_once()


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
    find(opened.window, QListWidget, "group_menu").setCurrentRow(10)
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
    find(opened.window, QListWidget, "group_menu").setCurrentRow(10)
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


# === 用語集のまとまり ===

GLOSSARY_GROUP_ROW = 7
"""まとまりのメニューの「用語集」の行。"""

CSV_FIVE_ROWS = "誤変換,正しい表記,使う\nあ,A,1\nい,B,1\nう,C,0\nえ,D,1\nお,E,0\n"
"""5 行（オン 3）の CSV（列 `使う` あり）。"""

CSV_TWO_ROWS = "誤変換,正しい表記\nか,K\nき,L\n"
"""2 行（オン 2）の CSV（列 `使う` なし。全ての行がオン）。"""

TWO_GLOSSARIES: dict[str, str | bytes | None] = {"yogo": CSV_FIVE_ROWS, "会議用": CSV_TWO_ROWS}
"""「yogo」「会議用」の 2 件の用語集（名前 → CSV の中身）。"""

SJIS_CSV = "誤変換,正しい表記\nか,K\n".encode("shift_jis")
"""UTF-8 でない CSV（読めない用語集を作る）。"""


def _open_glossaries(
    open_window: Callable[..., Opened],
    tmp_path: Path,
    files: dict[str, str | bytes | None],
    *,
    active: str | None = None,
    presets: list[tuple[str, list[str]]] | None = None,
    active_preset: str | None = None,
) -> Opened:
    """名前ごとの CSV を一時フォルダに書き、その一覧の用語集で設定画面を開いて、用語集のまとまりを選ぶ。

    行を読む関数と足す場所を決める関数と用語集のプリセットの一覧を引く関数は本物（read_glossary_rows・next_glossary_path・resolve_glossary_presets）を渡す。
    中身が None の CSV は書かない（フォルダを置いて開けない CSV にするときに使う）。
    presets は（プリセットの名前, 使う用語集の名前の並び）の並び。渡さなければ settings.toml に glossary_presets が無い形で、active は今までの active_glossary。
    """
    from functools import partial

    from voice_paste.features.correction import (
        next_glossary_path,
        read_glossary_rows,
        resolve_glossary_presets,
    )
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings

    glossaries = []
    for name, content in files.items():
        path = tmp_path / f"{name}.csv"
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif content is not None:
            path.write_text(content, encoding="utf-8")
        glossaries.append(GlossarySettings(name=name, path=path))
    settings = SETTINGS_MODEL(
        glossaries=glossaries,
        active_glossary=active,
        glossary_presets=[
            GlossaryPresetSettings(name=name, glossaries=names) for name, names in presets or []
        ],
        active_glossary_preset=active_preset,
    )
    opened = open_window(
        settings,
        list_glossaries=MagicMock(return_value=glossaries),
        list_glossary_presets=MagicMock(
            side_effect=lambda: resolve_glossary_presets(settings, tmp_path)
        ),
        read_glossary=read_glossary_rows,
        new_glossary_path=partial(next_glossary_path, directory=tmp_path / "glossaries"),
    )
    find(opened.window, QListWidget, "group_menu").setCurrentRow(GLOSSARY_GROUP_ROW)
    return opened


def _widgets(window: QWidget, cls: type, prefix: str) -> list[Any]:
    """objectName が prefix で始まる、画面に出ている部品を、名前の順で引く（作り直した前の部品は除く）。"""
    found = window.findChildren(cls, QRegularExpression(f"^{prefix}"))
    return sorted((widget for widget in found if widget.isVisible()), key=lambda widget: widget.objectName())


def _glossary_names(window: QWidget) -> list[str]:
    """用語集の一覧の名前のボタンの文字を、並びの順で返す。"""
    return [button.text() for button in _widgets(window, QPushButton, "glossary_pick_")]


def _count(window: QWidget, number: int) -> str:
    """number 件目の用語集の行の数の表示を返す。"""
    return find(window, QLabel, f"glossary_count_{number}").text()


def _saved(opened: Opened) -> tuple[Settings, dict[Path, list[Any]]]:
    """保存で書く設定と、書き戻す用語集の CSV（場所 → 行）を返す。"""
    saved, rows = opened.deps.save_settings.call_args.args
    return saved, rows


def _entry_checks(window: QWidget) -> list[bool]:
    """行の表の「使う」のチェックボックスの状態を、行の順で返す。"""
    return [box.isChecked() for box in _widgets(window, QCheckBox, "glossary_entry_on_")]


# === glossary_list ===


def test_glossary_list_when_visible(open_window: Callable[..., Opened]) -> None:
    """用語集の一覧は、用語集のまとまりを選んだときだけ出る。見出しは「用語集の一覧」。"""
    # 準備
    window = open_window().window
    list_frame = find(window, QFrame, "glossary_list")
    assert not list_frame.isVisible()

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(GLOSSARY_GROUP_ROW)

    # 検証
    assert list_frame.isVisible()
    assert _label_with_text(window, "用語集の一覧").isVisible()
    assert list_frame.accessibleName() == "用語集の一覧"
    assert not _field(window, "transcription.local_whisper.model").isVisible()


def test_glossary_list_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """一覧は settings.toml の glossaries の並びで 1 行ずつ出し、列は「名前」「使うプリセット」「行」と消すボタン。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    list_frame = find(opened.window, QFrame, "glossary_list")
    headings = [
        label.text() for label in list_frame.findChildren(QLabel) if label.property("role") == "heading"
    ]
    assert headings == ["名前", "使うプリセット", "行"]
    assert _glossary_names(opened.window) == ["yogo", "会議用"]
    assert len(_widgets(opened.window, QPushButton, "glossary_remove_")) == 2


def test_glossary_list_when_glossaries_empty(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """glossaries が空なら、glossary_path の CSV を 1 件目にし、名前を CSV のファイル名から拡張子を除いたものにする。"""
    from voice_paste.features.correction import read_glossary_rows, resolve_glossaries

    # 準備
    csv_file = tmp_path / "terms.csv"
    csv_file.write_text(CSV_TWO_ROWS, encoding="utf-8")
    settings = SETTINGS_MODEL(glossary_path=csv_file)

    # 実行
    opened = open_window(
        settings,
        list_glossaries=lambda: resolve_glossaries(settings, tmp_path),
        read_glossary=read_glossary_rows,
    )
    find(opened.window, QListWidget, "group_menu").setCurrentRow(GLOSSARY_GROUP_ROW)

    # 検証
    assert _glossary_names(opened.window) == ["terms"]
    assert _count(opened.window, 0) == "2 行（オン 2）"
    _click(opened.window, "save_button")
    saved, rows = _saved(opened)
    assert [glossary.name for glossary in saved.glossaries] == ["terms"]
    assert saved.glossaries[0].path == csv_file
    assert saved.glossary_path is None
    assert rows == {}


TWO_PRESETS: list[tuple[str, list[str]]] = [("既定", ["yogo"]), ("会議", ["会議用", "yogo"])]
"""「既定」（["yogo"]）と「会議」（["会議用", "yogo"]）の 2 件のプリセット（名前, 使う用語集の名前の並び）。"""

FAR_BELOW_Y = 100000
"""つまみを離した縦の位置のうち、どの行の中心よりも下になる値。"""


def _saved_presets(opened: Opened) -> list[tuple[str, list[str]]]:
    """保存で書く設定の用語集のプリセットを、（名前, 使う用語集の名前の並び）の並びで返す。"""
    saved, _rows = _saved(opened)
    return [(preset.name, preset.glossaries) for preset in saved.glossary_presets]


def _preset_names(window: QWidget) -> list[str]:
    """用語集のプリセットの一覧の名前のボタンの文字を、並びの順で返す。"""
    return [button.text() for button in _widgets(window, QPushButton, "glossary_preset_pick_")]


def _used_names(window: QWidget) -> list[str]:
    """使う用語集の表の用語集の名前を、表の順で返す（外すボタンの読み上げの名前「{用語集}を外す」から引く）。"""
    buttons = _widgets(window, QPushButton, "glossary_preset_glossary_remove_")
    return [button.accessibleName().removesuffix("を外す") for button in buttons]


def _select_texts(window: QWidget) -> list[str]:
    """追加する用語集の選択の選択肢の文字を、並びの順で返す（選択の欄が無ければ空）。"""
    combo = window.findChild(QComboBox, "glossary_preset_glossary_select")
    if combo is None:
        return []
    return [combo.itemText(index) for index in range(combo.count())]


def _add_use(window: QWidget, name: str) -> None:
    """追加する用語集の選択で name を選び、使う用語集の追加ボタンを押す。"""
    combo = find(window, QComboBox, "glossary_preset_glossary_select")
    combo.setCurrentIndex(combo.findText(name))
    _click(window, "glossary_preset_glossary_add")


def _preset_count(window: QWidget, number: int) -> str:
    """number 件目のプリセットの用語集の数の表示を返す。"""
    return find(window, QLabel, f"glossary_preset_count_{number}").text()


# === glossary_preset_list ===


def test_glossary_preset_list_when_visible(open_window: Callable[..., Opened]) -> None:
    """用語集のプリセットの一覧は、用語集のまとまりを選んだときだけ出る。見出しは「用語集のプリセット」。"""
    # 準備
    window = open_window().window
    list_frame = find(window, QFrame, "glossary_preset_list")
    assert not list_frame.isVisible()

    # 実行
    find(window, QListWidget, "group_menu").setCurrentRow(GLOSSARY_GROUP_ROW)

    # 検証
    assert list_frame.isVisible()
    assert _label_with_text(window, "用語集のプリセット").isVisible()
    assert list_frame.accessibleName() == "用語集のプリセットの一覧（補正に使うプリセットを 1 つ選ぶ）"


def test_glossary_preset_list_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """一覧は settings.toml の glossary_presets の並びで 1 行ずつ出し、列は「補正に使う」「名前」「用語集」と消すボタン。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 検証
    list_frame = find(opened.window, QFrame, "glossary_preset_list")
    headings = [
        label.text() for label in list_frame.findChildren(QLabel) if label.property("role") == "heading"
    ]
    assert headings == ["補正に使う", "名前", "用語集"]
    assert _preset_names(opened.window) == ["既定", "会議"]
    assert len(_widgets(opened.window, QPushButton, "glossary_preset_remove_")) == 2


@pytest.mark.parametrize(
    ("active", "used"),
    [
        pytest.param("会議用", ["会議用"], id="legacy_active"),
        pytest.param(None, ["yogo"], id="no_active"),
        pytest.param("存在しない名前", ["yogo"], id="unknown_active"),
    ],
)
def test_glossary_preset_list_when_presets_empty(
    open_window: Callable[..., Opened], tmp_path: Path, active: str | None, used: list[str]
) -> None:
    """glossary_presets が空なら、active_glossary の用語集だけを使う「既定」の 1 件を出す（無い・一覧に無ければ 1 つ目の用語集）。保存でこのキーを消して、プリセットの形に書く。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, active=active)

    # 検証
    assert _preset_names(opened.window) == ["既定"]
    assert _used_names(opened.window) == used
    _click(opened.window, "save_button")
    saved, _rows = _saved(opened)
    assert _saved_presets(opened) == [("既定", used)]
    assert saved.active_glossary_preset == "既定"
    assert saved.active_glossary is None


# === glossary_preset_active_{n} ===


@pytest.mark.parametrize(
    ("active", "checked"),
    [
        pytest.param("会議", [False, True], id="named"),
        pytest.param(None, [True, False], id="unset"),
        pytest.param("存在しない名前", [True, False], id="unknown"),
    ],
)
def test_glossary_preset_active_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path, active: str | None, checked: list[bool]
) -> None:
    """補正に使うプリセットは、settings.toml の active_glossary_preset の名前のプリセット。キーが無い・一覧に無ければ 1 件目。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset=active
    )

    # 検証
    radios = _widgets(opened.window, QRadioButton, "glossary_preset_active_")
    assert [radio.isChecked() for radio in radios] == checked
    assert [radio.accessibleName() for radio in radios] == ["既定を補正に使う", "会議を補正に使う"]


def test_glossary_preset_active_accessible_name_when_unnamed(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """名前が空のプリセットの読み上げの名前は「名前未入力のプリセットを補正に使う」。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行
    _click(opened.window, "add_glossary_preset_button")

    # 検証
    radio = find(opened.window, QRadioButton, "glossary_preset_active_2")
    assert radio.accessibleName() == "名前未入力のプリセットを補正に使う"


def test_glossary_preset_active_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """補正に使うプリセットは 1 つだけ選べ、選ぶと消すボタンの扱いが入れ替わり、保存で active_glossary_preset に書く。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行
    find(opened.window, QRadioButton, "glossary_preset_active_1").click()

    # 検証
    assert not find(opened.window, QRadioButton, "glossary_preset_active_0").isChecked()
    assert find(opened.window, QRadioButton, "glossary_preset_active_1").isChecked()
    assert find(opened.window, QPushButton, "glossary_preset_remove_0").toolTip() == ""
    remove_active = find(opened.window, QPushButton, "glossary_preset_remove_1")
    assert remove_active.toolTip() == "補正に使うプリセットは消せません"
    _click(opened.window, "save_button")
    assert _saved(opened)[0].active_glossary_preset == "会議"


# === glossary_preset_pick_{n} ===


def test_glossary_preset_pick_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """設定画面を開いたときは、補正に使うプリセットの使う用語集の表を出し、その 1 つ目の用語集の行の表を出している。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )

    # 検証
    assert find(opened.window, QLineEdit, "glossary_preset_name_1").text() == "会議"
    assert _used_names(opened.window) == ["会議用", "yogo"]
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「会議用」の行"


def test_glossary_preset_pick_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """名前のボタンを押すと、そのプリセットの使う用語集の表を下に出す。切り替えても入れた値は消さない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    find(opened.window, QLineEdit, "glossary_preset_name_0").setText("変えた名前")

    # 実行
    _click(opened.window, "glossary_preset_pick_1")

    # 検証
    assert find(opened.window, QLineEdit, "glossary_preset_name_1").text() == "会議"
    assert _used_names(opened.window) == ["会議用", "yogo"]
    _click(opened.window, "glossary_preset_pick_0")
    assert find(opened.window, QLineEdit, "glossary_preset_name_0").text() == "変えた名前"


def test_glossary_preset_pick_when_name_unnamed_or_long(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """名前が空なら「名前未入力のプリセット」、長い名前は 1 行に収めて末尾を省く。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行
    find(opened.window, QLineEdit, "glossary_preset_name_0").setText("")
    _click(opened.window, "glossary_preset_pick_1")
    find(opened.window, QLineEdit, "glossary_preset_name_1").setText(
        "とても長いプリセットの名前をつけたので一覧では途中で省かれる"
    )

    # 検証
    names = _preset_names(opened.window)
    assert names[0] == "名前未入力のプリセット"
    assert names[1].endswith("…")
    assert len(names[1]) <= 20


# === glossary_preset_count_{n} ===


def test_glossary_preset_count_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集の数は「{数} 件」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 検証
    assert _preset_count(opened.window, 0) == "1 件"
    assert _preset_count(opened.window, 1) == "2 件"


def test_glossary_preset_count_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """使う用語集を追加・外すたびに数え直す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行・検証
    _add_use(opened.window, "会議用")
    assert _preset_count(opened.window, 0) == "2 件"
    _click(opened.window, "glossary_preset_glossary_remove_0")
    assert _preset_count(opened.window, 0) == "1 件"


# === glossary_preset_remove_{n} ===


def test_glossary_preset_remove_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """プリセットを一覧から消す。用語集は消さず、保存するまで settings.toml に書かない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行
    _click(opened.window, "glossary_preset_remove_1")

    # 検証
    assert _preset_names(opened.window) == ["既定"]
    assert _glossary_names(opened.window) == ["yogo", "会議用"]
    opened.deps.save_settings.assert_not_called()
    _click(opened.window, "save_button")
    assert _saved_presets(opened) == [("既定", ["yogo"])]


def test_glossary_preset_remove_when_cancelled(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """消した後にキャンセルで閉じれば、settings.toml には書かない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    _click(opened.window, "glossary_preset_remove_1")
    driver = ModalDriver()
    driver.answer("discard_button")

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    opened.deps.save_settings.assert_not_called()
    opened.closed.assert_called_once()


def test_glossary_preset_remove_when_active(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """補正に使うプリセットの消すボタンは、薄くして押しても消さず、フォーカスは受けてツールチップを出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    button = find(opened.window, QPushButton, "glossary_preset_remove_0")

    # 実行
    _click(opened.window, "glossary_preset_remove_0")

    # 検証
    assert _preset_names(opened.window) == ["既定", "会議"]
    assert button.isEnabled()
    assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert button.toolTip() == "補正に使うプリセットは消せません"
    assert button.graphicsEffect() is not None


def test_glossary_preset_remove_when_shown(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集の表を出しているプリセットを消したら、補正に使うプリセットの表を出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    _click(opened.window, "glossary_preset_pick_1")

    # 実行
    _click(opened.window, "glossary_preset_remove_1")

    # 検証
    assert find(opened.window, QLineEdit, "glossary_preset_name_0").text() == "既定"
    assert _used_names(opened.window) == ["yogo"]


def test_glossary_preset_remove_accessible_name(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """消すボタンの読み上げの名前は「{名前}を消す」（名前が空なら「名前未入力のプリセットを消す」）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行
    _click(opened.window, "add_glossary_preset_button")

    # 検証
    buttons = _widgets(opened.window, QPushButton, "glossary_preset_remove_")
    assert [button.accessibleName() for button in buttons] == [
        "既定を消す",
        "会議を消す",
        "名前未入力のプリセットを消す",
    ]


# === add_glossary_preset_button ===


def test_add_glossary_preset_button_action(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集が無く名前が空のプリセットを末尾に足し、その表を出して名前の欄へフォーカスを移す。補正に使うプリセットは変えない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    assert find(opened.window, QPushButton, "add_glossary_preset_button").text() == "プリセット追加"

    # 実行
    _click(opened.window, "add_glossary_preset_button")

    # 検証
    assert _preset_names(opened.window) == ["既定", "会議", "名前未入力のプリセット"]
    name_edit = find(opened.window, QLineEdit, "glossary_preset_name_2")
    assert name_edit.text() == ""
    assert opened.window.focusWidget() is name_edit
    assert find(opened.window, QLabel, "glossary_preset_glossaries_empty").isVisible()
    assert find(opened.window, QRadioButton, "glossary_preset_active_0").isChecked()


def test_add_glossary_preset_button_when_saved(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """足したプリセットは、保存で一覧の末尾に、使う用語集の無い形で書く。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    _click(opened.window, "add_glossary_preset_button")
    find(opened.window, QLineEdit, "glossary_preset_name_2").setText("議事録")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _saved_presets(opened) == [*TWO_PRESETS, ("議事録", [])]


# === glossary_preset_detail_title・glossary_preset_name_{n} ===


def test_glossary_preset_name_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """名前の欄はプリセットの名前で、見出しは「プリセット「{名前}」で使う用語集」。プレースホルダは「例: 会議」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 検証
    name_edit = find(opened.window, QLineEdit, "glossary_preset_name_0")
    assert name_edit.text() == "既定"
    assert name_edit.placeholderText() == "例: 会議"
    title = find(opened.window, QLabel, "glossary_preset_detail_title")
    assert title.text() == "プリセット「既定」で使う用語集"


def test_glossary_preset_name_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """入れた名前を、一覧の名前のボタンと見出しにすぐ出す（空なら「名前未入力のプリセット」）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    name_edit = find(opened.window, QLineEdit, "glossary_preset_name_0")
    title = find(opened.window, QLabel, "glossary_preset_detail_title")

    # 実行・検証
    name_edit.setText("議事録")
    assert _preset_names(opened.window)[0] == "議事録"
    assert title.text() == "プリセット「議事録」で使う用語集"
    name_edit.setText("")
    assert _preset_names(opened.window)[0] == "名前未入力のプリセット"
    assert title.text() == "名前未入力のプリセットで使う用語集"


def test_glossary_preset_name_when_saved(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """保存では名前の前後の空白を除く。補正に使うプリセットの名前を変えても、補正に使うプリセットのまま。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    find(opened.window, QLineEdit, "glossary_preset_name_0").setText("  議事録  ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _saved_presets(opened) == [("議事録", ["yogo"]), ("会議", ["会議用", "yogo"])]
    assert _saved(opened)[0].active_glossary_preset == "議事録"


# === glossary_preset_glossaries ===


def test_glossary_preset_glossaries_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集の表は、プリセットが使う用語集を当てる順に並べ、列は「順」「用語集」「行」と外すボタン。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )

    # 検証
    table = find(opened.window, QFrame, "glossary_preset_glossaries")
    assert table.isVisible()
    assert table.accessibleName() == "プリセットで使う用語集（上の用語集から順に当てる）"
    headings = [
        label.text() for label in table.findChildren(QLabel) if label.property("role") == "heading"
    ]
    assert headings == ["順", "用語集", "行"]
    assert _used_names(opened.window) == ["会議用", "yogo"]


def test_glossary_preset_glossaries_when_empty(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集が 0 件のプリセットでは、表を出さず、代わりに文を出す。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=[("空", []), ("既定", ["yogo"])]
    )

    # 実行・検証
    assert opened.window.findChild(QFrame, "glossary_preset_glossaries") is None
    _click(opened.window, "glossary_preset_pick_1")
    assert find(opened.window, QFrame, "glossary_preset_glossaries").isVisible()


# === glossary_preset_glossary_grip_{n} ===


def test_glossary_preset_glossary_grip_action(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """つまみを掴んで下へ離すと、行をそこへ動かして順の列を振り直す。保存で、並べた順に書く。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )
    grips = _widgets(opened.window, QLabel, "glossary_preset_glossary_grip_")
    assert [grip.toolTip() for grip in grips] == ["掴んで動かす", "掴んで動かす"]

    # 実行
    grips[0].released.emit(FAR_BELOW_Y)

    # 検証
    assert _used_names(opened.window) == ["yogo", "会議用"]
    _click(opened.window, "save_button")
    assert _saved_presets(opened)[1] == ("会議", ["yogo", "会議用"])


@pytest.mark.parametrize(
    ("row", "key", "expected"),
    [
        pytest.param(0, Qt.Key.Key_Down, ["yogo", "会議用"], id="down"),
        pytest.param(1, Qt.Key.Key_Up, ["yogo", "会議用"], id="up"),
        pytest.param(0, Qt.Key.Key_Up, ["会議用", "yogo"], id="up_at_top"),
        pytest.param(1, Qt.Key.Key_Down, ["会議用", "yogo"], id="down_at_bottom"),
    ],
)
def test_glossary_preset_glossary_grip_when_alt_arrow(
    open_window: Callable[..., Opened],
    tmp_path: Path,
    row: int,
    key: Qt.Key,
    expected: list[str],
) -> None:
    """行の外すボタンにフォーカスして Alt+↑ / Alt+↓ を押すと、行を 1 つ動かす（先頭の上・末尾の下へは動かさない）。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )
    button = find(opened.window, QPushButton, f"glossary_preset_glossary_remove_{row}")

    # 実行
    QTest.keyClick(button, key, Qt.KeyboardModifier.AltModifier)

    # 検証
    assert _used_names(opened.window) == expected


# === glossary_preset_glossary_remove_{n} ===


def test_glossary_preset_glossary_remove_action(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集をこのプリセットから外す。用語集そのものは消さず、追加する用語集の選択肢へ戻す。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )
    assert _select_texts(opened.window) == []

    # 実行
    _click(opened.window, "glossary_preset_glossary_remove_0")

    # 検証
    assert _used_names(opened.window) == ["yogo"]
    assert _select_texts(opened.window) == ["会議用"]
    assert _glossary_names(opened.window) == ["yogo", "会議用"]
    _click(opened.window, "save_button")
    assert _saved_presets(opened)[1] == ("会議", ["yogo"])


def test_glossary_preset_glossary_remove_accessible_name(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """外すボタンの読み上げの名前は「{用語集}を外す」、つまみは「{用語集}を動かす」。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )

    # 検証
    grips = _widgets(opened.window, QLabel, "glossary_preset_glossary_grip_")
    assert _used_names(opened.window) == ["会議用", "yogo"]
    assert [grip.accessibleName() for grip in grips] == ["会議用を動かす", "yogoを動かす"]


# === glossary_preset_glossaries_empty ===


def test_glossary_preset_glossaries_empty_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集が 0 件のときの文は「使う用語集がありません。このプリセットでは何も置き換えません。」。1 件以上あれば出さない。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=[("空", []), ("既定", ["yogo"])]
    )

    # 実行・検証
    empty = find(opened.window, QLabel, "glossary_preset_glossaries_empty")
    assert empty.isVisible()
    assert empty.text() == "使う用語集がありません。このプリセットでは何も置き換えません。"
    _click(opened.window, "glossary_preset_pick_1")
    assert opened.window.findChild(QLabel, "glossary_preset_glossaries_empty") is None


# === glossary_preset_glossary_select・glossary_preset_glossary_add ===


def test_glossary_preset_glossary_select_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """追加する用語集の選択は、このプリセットがまだ使っていない用語集を用語集の一覧の順に並べる。既定は 1 件目。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=[("空", []), ("既定", ["yogo"])]
    )

    # 検証
    combo = find(opened.window, QComboBox, "glossary_preset_glossary_select")
    assert combo.isVisible()
    assert _select_texts(opened.window) == ["yogo", "会議用"]
    assert combo.currentIndex() == 0
    assert find(opened.window, QPushButton, "glossary_preset_glossary_add").text() == "追加"


def test_glossary_preset_glossary_add_action(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """選んだ用語集を使う用語集の表の末尾に足し、選択肢から除く。保存で、足した順に書く。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=[("空", [])], active_preset="空"
    )

    # 実行
    _add_use(opened.window, "会議用")
    _add_use(opened.window, "yogo")

    # 検証
    assert _used_names(opened.window) == ["会議用", "yogo"]
    assert _select_texts(opened.window) == []
    _click(opened.window, "save_button")
    assert _saved_presets(opened) == [("空", ["会議用", "yogo"])]


def test_glossary_preset_glossary_select_when_unnamed_glossary(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """足しただけで名前が空の用語集は、どのプリセットの使う用語集にも入らず、選択肢に「（名前未入力）」で出る。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行
    _click(opened.window, "add_glossary_button")

    # 検証
    assert _used_names(opened.window) == ["yogo"]
    assert _select_texts(opened.window) == ["会議用", "（名前未入力）"]


# === glossary_preset_glossaries_all ===


def test_glossary_preset_glossaries_all_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集の一覧の全てを使っているときは、追加する用語集の選択と追加ボタンの代わりに「全ての用語集を使っています。」を出す。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )

    # 検証
    all_used = find(opened.window, QLabel, "glossary_preset_glossaries_all")
    assert all_used.isVisible()
    assert all_used.text() == "全ての用語集を使っています。"
    assert opened.window.findChild(QComboBox, "glossary_preset_glossary_select") is None
    assert opened.window.findChild(QPushButton, "glossary_preset_glossary_add") is None
    _click(opened.window, "glossary_preset_pick_0")
    assert opened.window.findChild(QLabel, "glossary_preset_glossaries_all") is None


# === glossary_preset_rule_note ===


def test_glossary_preset_rule_note_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """使う用語集の決まりの凡例は、当てる順と並べ替えの操作を示し、使う用語集の表の下端に出す。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 検証
    note = find(opened.window, QLabel, "glossary_preset_rule_note")
    assert note.isVisible()
    assert note.text() == (
        "上の用語集から順に当てる。同じ誤変換は上の用語集の行が当たる。"
        "行は左端を掴むか、Alt+↑ / Alt+↓ で動かす。"
    )
    table = find(opened.window, QFrame, "glossary_preset_glossaries")
    assert _top_of(note, opened.window) > _top_of(table, opened.window)


# === glossary_presets_using_{n} ===


def test_glossary_presets_using_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集を使っているプリセットの名前を、プリセットの一覧の順に「・」で結んで出す。どのプリセットも使っていなければ「なし」。"""
    # 実行
    opened = _open_glossaries(
        open_window,
        tmp_path,
        TWO_GLOSSARIES,
        presets=[("既定", ["yogo"]), ("会議", ["yogo"])],
    )

    # 検証
    assert find(opened.window, QLabel, "glossary_presets_using_0").text() == "既定・会議"
    assert find(opened.window, QLabel, "glossary_presets_using_1").text() == "なし"


def test_glossary_presets_using_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """プリセットに用語集を追加・外す、プリセットの名前を変えると、使うプリセットの表示も変わる。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 実行・検証
    _add_use(opened.window, "会議用")
    assert find(opened.window, QLabel, "glossary_presets_using_1").text() == "既定・会議"
    find(opened.window, QLineEdit, "glossary_preset_name_0").setText("共通")
    assert find(opened.window, QLabel, "glossary_presets_using_0").text() == "共通・会議"
    _click(opened.window, "glossary_preset_glossary_remove_0")
    assert find(opened.window, QLabel, "glossary_presets_using_0").text() == "会議"


# === glossary_list_note ===


def test_glossary_list_note_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集の一覧の決まりは「消した用語集は、使っているプリセットからも外れる。」で、用語集追加のボタンの右に出す。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)

    # 検証
    note = find(opened.window, QLabel, "glossary_list_note")
    button = find(opened.window, QPushButton, "add_glossary_button")
    assert note.isVisible()
    assert note.text() == "消した用語集は、使っているプリセットからも外れる。"
    assert _top_of(note, opened.window) <= _top_of(button, opened.window) + button.height()
    assert _left_of(note, opened.window) >= _left_of(button, opened.window) + button.width()


def test_glossary_remove_when_used_by_presets(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集を消すと、その用語集を使っているプリセットの使う用語集からも外れる。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset="会議"
    )

    # 実行
    _click(opened.window, "glossary_remove_1")

    # 検証
    assert _used_names(opened.window) == ["yogo"]
    assert find(opened.window, QLabel, "glossary_presets_using_0").text() == "既定・会議"
    _click(opened.window, "save_button")
    assert _saved_presets(opened) == [("既定", ["yogo"]), ("会議", ["yogo"])]


# === glossary_pick_{n} ===


def test_glossary_pick_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """設定画面を開いたときは、補正に使うプリセットの 1 つ目の用語集の名前の欄と行の表を出している。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=[("既定", ["会議用"])])

    # 検証
    assert find(opened.window, QLineEdit, "glossary_name_1").text() == "会議用"
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「会議用」の行"
    assert len(_widgets(opened.window, QLineEdit, "glossary_entry_wrong_")) == 2


def test_glossary_pick_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """名前のボタンを押すと、その用語集の名前の欄と行の表を下に出す。切り替えても入れた値は消さない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")[0].setText("変えた")

    # 実行
    _click(opened.window, "glossary_pick_1")

    # 検証
    assert find(opened.window, QLineEdit, "glossary_name_1").text() == "会議用"
    assert [edit.text() for edit in _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")] == ["か", "き"]
    _click(opened.window, "glossary_pick_0")
    assert _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")[0].text() == "変えた"


def test_glossary_pick_when_name_unnamed_or_long(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """名前が空なら「（名前未入力）」、長い名前は 1 行に収めて末尾を省く。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 実行
    find(opened.window, QLineEdit, "glossary_name_0").setText("")
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QLineEdit, "glossary_name_1").setText("とても長い用語集の名前をつけたので一覧では途中で省かれる")

    # 検証
    names = _glossary_names(opened.window)
    assert names[0] == "（名前未入力）"
    assert names[1].endswith("…")
    assert len(names[1]) <= 20


# === glossary_count_{n} ===


def test_glossary_count_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行の数は「{行の数} 行（オン {オンの行の数}）」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    assert _count(opened.window, 0) == "5 行（オン 3）"
    assert _count(opened.window, 1) == "2 行（オン 2）"


def test_glossary_count_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行を足す・消す・オンとオフを切り替えるたびに数え直す（足した両方が空の行も数える）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 実行・検証
    _click(opened.window, "add_glossary_entry_button")
    assert _count(opened.window, 0) == "6 行（オン 4）"
    find(opened.window, QCheckBox, "glossary_entry_on_0").click()
    assert _count(opened.window, 0) == "6 行（オン 3）"
    _click(opened.window, "glossary_entry_remove_1")
    assert _count(opened.window, 0) == "5 行（オン 2）"


def test_glossary_count_when_unreadable(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """CSV を読めなかった用語集の行の数は「読めません」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "壊れた": SJIS_CSV})

    # 検証
    assert _count(opened.window, 1) == "読めません"


# === glossary_remove_{n} ===


def test_glossary_remove_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集を一覧から消す。CSV のファイルは消さず、保存するまで settings.toml に書かず、キャンセルで戻せる。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 実行
    _click(opened.window, "glossary_remove_1")

    # 検証（消えた。CSV は残る。保存しても書き戻す CSV は無い）
    assert _glossary_names(opened.window) == ["yogo"]
    assert (tmp_path / "会議用.csv").exists()
    opened.deps.save_settings.assert_not_called()
    _click(opened.window, "save_button")
    saved, rows = _saved(opened)
    assert [glossary.name for glossary in saved.glossaries] == ["yogo"]
    assert rows == {}


def test_glossary_remove_when_cancelled(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """消した後にキャンセルで閉じれば、settings.toml には書かない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "glossary_remove_1")
    driver = ModalDriver()
    driver.answer("discard_button")

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    opened.deps.save_settings.assert_not_called()
    opened.closed.assert_called_once()


def test_glossary_remove_when_last(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """最後の 1 件の用語集の消すボタンは、薄くして押しても消さず、フォーカスは受けてツールチップ「最後の用語集は消せません」を出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS})
    button = find(opened.window, QPushButton, "glossary_remove_0")

    # 実行
    _click(opened.window, "glossary_remove_0")

    # 検証
    assert _glossary_names(opened.window) == ["yogo"]
    assert button.isEnabled()
    assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert button.toolTip() == "最後の用語集は消せません"
    assert button.graphicsEffect() is not None


def test_glossary_remove_when_two(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集が 2 件以上あるときは、どの用語集の消すボタンも押せる（補正に使うプリセットが使う用語集も消せる）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 実行
    buttons = _widgets(opened.window, QPushButton, "glossary_remove_")

    # 検証
    assert [button.toolTip() for button in buttons] == ["", ""]
    assert [button.graphicsEffect() is None for button in buttons] == [True, True]
    _click(opened.window, "glossary_remove_0")
    assert _glossary_names(opened.window) == ["会議用"]
    assert find(opened.window, QPushButton, "glossary_remove_0").toolTip() == "最後の用語集は消せません"


def test_glossary_remove_when_shown(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行の表を出している用語集を消したら、補正に使う用語集の行の表を出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "glossary_pick_1")

    # 実行
    _click(opened.window, "glossary_remove_1")

    # 検証
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「yogo」の行"


def test_glossary_remove_accessible_name(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """消すボタンの読み上げの名前は「{名前}を消す」（名前が空なら「名前未入力の用語集を消す」）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 実行
    _click(opened.window, "add_glossary_button")

    # 検証
    names = [button.accessibleName() for button in _widgets(opened.window, QPushButton, "glossary_remove_")]
    assert names == ["yogoを消す", "会議用を消す", "名前未入力の用語集を消す"]


# === discard_body（用語集の変更の件数） ===


def _discard_body(opened: Opened) -> str:
    """「キャンセル」を押して出た確認の本文を控え、「設定画面へ戻る」で閉じて、本文を返す。"""
    seen: dict[str, str] = {}

    def _inspect(box: QMessageBox) -> None:
        """出た確認の本文を控える。"""
        seen["body"] = box.informativeText()

    driver = ModalDriver()
    driver.answer("back_button", _inspect)
    _click(opened.window, "cancel_button")
    driver.verify()
    return seen["body"]


def _discard_message(count: int) -> str:
    """変えた欄が count 件のときの、確認の本文。"""
    return f"保存していない変更が {count} 件あります。閉じると、変えた値は保存されません。"


def test_discard_body_when_glossary_added(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集を 1 つ足すと、変えた件数は 1 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "add_glossary_button")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_glossary_removed(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集を 1 つ消すと、変えた件数は 1 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "glossary_remove_1")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_glossary_renamed(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集の名前だけを変えると、変えた件数は 1 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QLineEdit, "glossary_name_1").setText("議事録")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_rows_changed_twice(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """1 つの用語集の行を 2 か所変えても、変えた件数は 1 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    wrong_edits = _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")
    wrong_edits[0].setText("変えた1")
    wrong_edits[1].setText("変えた2")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_rows_changed_in_two_glossaries(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """2 つの用語集の行をそれぞれ変えると、変えた件数は 2 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")[0].setText("変えた1")
    _click(opened.window, "glossary_pick_1")
    _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")[0].setText("変えた2")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(2)


def test_discard_body_when_active_switched(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """補正に使うプリセットを切り替えると、変えた件数は 1 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    find(opened.window, QRadioButton, "glossary_preset_active_1").click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_active_renamed(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """補正に使うプリセットの名前だけを変えると、変えた件数は 1 件（切り替えとして数えない）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    find(opened.window, QLineEdit, "glossary_preset_name_0").setText("改名")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_added_and_active(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """プリセットを足してそのプリセットを補正に使うと、変えた件数は 2 件。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    _click(opened.window, "add_glossary_preset_button")
    find(opened.window, QRadioButton, "glossary_preset_active_2").click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(2)


def test_discard_body_when_glossary_renamed_and_used_by_preset(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """プリセットが使う用語集の名前だけを変えると、変えた件数は 1 件（プリセットの変更として数えない）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    find(opened.window, QLineEdit, "glossary_name_0").setText("改名")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


@pytest.mark.parametrize(
    ("active_preset", "operation"),
    [
        pytest.param(
            "既定", lambda window: _click(window, "add_glossary_preset_button"), id="preset_added"
        ),
        pytest.param(
            "既定", lambda window: _click(window, "glossary_preset_remove_1"), id="preset_removed"
        ),
        pytest.param(
            "既定",
            lambda window: find(window, QLineEdit, "glossary_preset_name_0").setText("改名"),
            id="preset_renamed",
        ),
        pytest.param("既定", lambda window: _add_use(window, "会議用"), id="use_added"),
        pytest.param(
            "既定",
            lambda window: _click(window, "glossary_preset_glossary_remove_0"),
            id="use_removed",
        ),
        pytest.param(
            "会議",
            lambda window: _widgets(window, QLabel, "glossary_preset_glossary_grip_")[0]
            .released.emit(FAR_BELOW_Y),
            id="use_moved",
        ),
    ],
)
def test_discard_body_when_preset_changed(
    open_window: Callable[..., Opened],
    tmp_path: Path,
    active_preset: str,
    operation: Callable[[QWidget], None],
) -> None:
    """プリセットを足す・消す・名前を変える、使う用語集を追加する・外す・動かすのどれでも、変えた件数は 1 件。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS, active_preset=active_preset
    )
    operation(opened.window)

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


# === add_glossary_button ===


def test_add_glossary_button_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """名前が空で行の無い用語集を末尾に足し、その行の表を出して名前の欄へフォーカスを移す。どのプリセットの使う用語集にも入れない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    assert find(opened.window, QPushButton, "add_glossary_button").text() == "用語集追加"

    # 実行
    _click(opened.window, "add_glossary_button")

    # 検証
    assert _glossary_names(opened.window) == ["yogo", "会議用", "（名前未入力）"]
    name_edit = find(opened.window, QLineEdit, "glossary_name_2")
    assert name_edit.text() == ""
    assert opened.window.focusWidget() is name_edit
    assert find(opened.window, QLabel, "glossary_entries_empty").isVisible()
    assert find(opened.window, QRadioButton, "glossary_preset_active_0").isChecked()
    assert find(opened.window, QLabel, "glossary_presets_using_2").text() == "なし"


def test_add_glossary_button_when_saved(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """足した用語集は、保存で一覧に書き、CSV は設定ファイルと同じフォルダの glossaries の下に作る（書き戻しに渡す）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "add_glossary_button")
    find(opened.window, QLineEdit, "glossary_name_2").setText("新しい用語集")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved, rows = _saved(opened)
    new_path = tmp_path / "glossaries" / "glossary_1.csv"
    assert [glossary.name for glossary in saved.glossaries] == ["yogo", "会議用", "新しい用語集"]
    assert saved.glossaries[2].path == new_path
    assert rows == {new_path: []}


# === glossary_detail_title・glossary_name_{n} ===


def test_glossary_name_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """名前の欄は用語集の名前で、見出しは「用語集「{名前}」の行」。プレースホルダは「例: 会議用」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    name_edit = find(opened.window, QLineEdit, "glossary_name_0")
    assert name_edit.text() == "yogo"
    assert name_edit.placeholderText() == "例: 会議用"
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「yogo」の行"


def test_glossary_name_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """入れた名前を、一覧の名前のボタンと行の見出しにも出す（空なら「（名前未入力）」）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    name_edit = find(opened.window, QLineEdit, "glossary_name_0")

    # 実行・検証
    name_edit.setText("議事録")
    assert _glossary_names(opened.window)[0] == "議事録"
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「議事録」の行"
    name_edit.setText("")
    assert _glossary_names(opened.window)[0] == "（名前未入力）"
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「（名前未入力）」の行"


def test_glossary_name_when_saved(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """保存では名前の前後の空白を除き、その用語集を使うプリセットも新しい名前で書く。名前だけ変えた用語集の CSV は書き戻さない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_name_0").setText("  議事録  ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved, rows = _saved(opened)
    assert [glossary.name for glossary in saved.glossaries] == ["議事録", "会議用"]
    assert _saved_presets(opened) == [("既定", ["議事録"])]
    assert rows == {}


# === glossary_entries・glossary_entries_empty ===


def test_glossary_entries_when_visible(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行の表は、行の表を出している用語集に行が 1 つ以上あるときだけ出す。行が 1 つも無ければ代わりに文を出す。"""
    # 準備
    header_only = "誤変換,正しい表記\n"
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "空": header_only})

    # 実行・検証
    table = find(opened.window, QFrame, "glossary_entries")
    assert table.isVisible()
    assert table.accessibleName() == "用語集の行（上の行から順に置き換える）"
    assert opened.window.findChild(QLabel, "glossary_entries_empty") is None
    _click(opened.window, "glossary_pick_1")
    assert opened.window.findChild(QFrame, "glossary_entries") is None
    empty = find(opened.window, QLabel, "glossary_entries_empty")
    assert empty.isVisible()
    assert empty.text() == "この用語集にはまだ行がありません。"


def test_glossary_entries_empty_position(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行が無いときの文は、消す行の説明の下に出す（行が 0 の用語集で、説明が上に出る）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, {"空": "誤変換,正しい表記\n"})

    # 実行・検証
    assert _detail_order(opened.window, "glossary_delete_note", "glossary_entries_empty") == [
        "glossary_delete_note",
        "glossary_entries_empty",
    ]


# === glossary_delete_note ===


def _detail_order(window: QWidget, *names: str) -> list[str]:
    """用語集の行の欄に並ぶ部品のうち、objectName が names のものを、上から並んでいる順で返す。"""
    parent = find(window, QLabel, "glossary_detail_title").parentWidget()
    layout = parent.layout()
    positions = {}
    for name in names:
        widget = parent.findChild(QWidget, name)
        # 入れ子の中にある部品は、行の欄の直下の部品の位置で比べる
        while widget.parentWidget() is not parent:
            widget = widget.parentWidget()
        positions[name] = layout.indexOf(widget)
    return sorted(names, key=lambda name: positions[name])


def test_glossary_delete_note_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """消す行の説明は「正しい表記を空にすると、誤変換を消す。」で、名前の欄の下・行の表の上に出す。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    note = find(opened.window, QLabel, "glossary_delete_note")
    assert note.isVisible()
    assert note.text() == "正しい表記を空にすると、誤変換を消す。"
    assert _detail_order(
        opened.window, "glossary_name_0", "glossary_delete_note", "glossary_entries"
    ) == ["glossary_name_0", "glossary_delete_note", "glossary_entries"]


def test_glossary_delete_note_when_unreadable(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """CSV を読めなかった用語集の行の表を出しているときは、消す行の説明を出さない。読めた用語集へ戻れば出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "壊れた": SJIS_CSV})

    # 実行
    _click(opened.window, "glossary_pick_1")

    # 検証
    assert opened.window.findChild(QLabel, "glossary_delete_note") is None
    _click(opened.window, "glossary_pick_0")
    assert find(opened.window, QLabel, "glossary_delete_note").isVisible()


# === glossary_entry_on_{n} ===


def test_glossary_entry_on_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行のオン・オフは CSV の値（列 `使う` が 0 の行がオフ。列が無い行はオン）。読み上げの名前は「{何行目か} 行目を補正に使う」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    assert _entry_checks(opened.window) == [True, True, False, True, False]
    first = find(opened.window, QCheckBox, "glossary_entry_on_0")
    assert first.accessibleName() == "1 行目を補正に使う"
    _click(opened.window, "glossary_pick_1")
    assert _entry_checks(opened.window) == [True, True]


def test_glossary_entry_on_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """切り替えると、オフの行の文字を薄くして取り消し線を引き（色だけで伝えない）、保存で CSV の行のオン・オフに書き戻す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    wrong_edits = _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")
    assert wrong_edits[2].font().strikeOut()
    assert not wrong_edits[0].font().strikeOut()

    # 実行
    find(opened.window, QCheckBox, "glossary_entry_on_0").click()

    # 検証
    assert wrong_edits[0].font().strikeOut()
    assert wrong_edits[0].graphicsEffect() is not None
    _click(opened.window, "save_button")
    rows = _saved(opened)[1]
    assert [entry.enabled for entry in rows[tmp_path / "yogo.csv"]] == [False, True, False, True, False]


# === glossary_entry_wrong_{n}・glossary_entry_right_{n} ===


def test_glossary_entry_fields_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """誤変換と正しい表記の欄は CSV の値。読み上げの名前は「{何行目か} 行目の誤変換」「{何行目か} 行目の正しい表記」。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    wrong = find(opened.window, QLineEdit, "glossary_entry_wrong_1")
    right = find(opened.window, QLineEdit, "glossary_entry_right_1")
    assert (wrong.text(), right.text()) == ("い", "B")
    assert wrong.accessibleName() == "2 行目の誤変換"
    assert right.accessibleName() == "2 行目の正しい表記"


def test_glossary_entry_fields_when_saved(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """保存では前後の空白を除いて、行を変えた用語集の CSV の行へ書き戻す（行を変えていない用語集は書き戻さない）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_entry_wrong_0").setText("  くろーど  ")
    find(opened.window, QLineEdit, "glossary_entry_right_0").setText("  Claude  ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    rows = _saved(opened)[1]
    assert list(rows) == [tmp_path / "yogo.csv"]
    assert (rows[tmp_path / "yogo.csv"][0].wrong, rows[tmp_path / "yogo.csv"][0].right) == ("くろーど", "Claude")


# === glossary_entry_remove_{n} ===


def test_glossary_entry_remove_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """行を表から消す。保存するまで CSV には書かず、保存で消した行を除いて書き戻す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    assert find(opened.window, QPushButton, "glossary_entry_remove_0").accessibleName() == "1 行目を消す"

    # 実行
    _click(opened.window, "glossary_entry_remove_0")

    # 検証
    assert [edit.text() for edit in _widgets(opened.window, QLineEdit, "glossary_entry_wrong_")] == ["い", "う", "え", "お"]
    assert (tmp_path / "yogo.csv").read_text(encoding="utf-8") == CSV_FIVE_ROWS
    _click(opened.window, "save_button")
    assert [entry.wrong for entry in _saved(opened)[1][tmp_path / "yogo.csv"]] == ["い", "う", "え", "お"]


# === add_glossary_entry_button ===


def test_add_glossary_entry_button_action(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """誤変換と正しい表記が空でオンの行を表の末尾に足し、その行の誤変換の欄へフォーカスを移す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    assert find(opened.window, QPushButton, "add_glossary_entry_button").text() == "行追加"

    # 実行
    _click(opened.window, "add_glossary_entry_button")

    # 検証
    assert _entry_checks(opened.window) == [True, True, False, True, False, True]
    wrong = find(opened.window, QLineEdit, "glossary_entry_wrong_5")
    assert (wrong.text(), find(opened.window, QLineEdit, "glossary_entry_right_5").text()) == ("", "")
    assert opened.window.focusWidget() is wrong


def test_add_glossary_entry_button_when_added_glossary(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """足した用語集でも行を足せる。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "add_glossary_button")

    # 実行
    _click(opened.window, "add_glossary_entry_button")

    # 検証
    assert find(opened.window, QPushButton, "add_glossary_entry_button").isEnabled()
    assert len(_widgets(opened.window, QLineEdit, "glossary_entry_wrong_")) == 1
    assert opened.window.findChild(QLabel, "glossary_entries_empty") is None


# === glossary_legend ===


def test_glossary_legend_initial_value(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """補正の決まりの凡例は、用語集のまとまりを選んだときに出す。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)

    # 検証
    legend = find(opened.window, QLabel, "glossary_legend")
    assert legend.isVisible()
    assert legend.text() == "上の行から順に置き換える。オフの行は補正に使わない。"


# === glossary_unreadable ===


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        pytest.param(SJIS_CSV, "文字コードが UTF-8 ではありません", id="not_utf8"),
        pytest.param("くろーど,Claude\n", "見出しに「誤変換」「正しい表記」の列がありません", id="no_header"),
        pytest.param('誤変換,正しい表記\nあ,"' + "x" * 200000, "CSV の書式が正しくありません（", id="malformed"),
    ],
)
def test_glossary_unreadable_initial_value(
    open_window: Callable[..., Opened], tmp_path: Path, content: str | bytes, reason: str
) -> None:
    """CSV を読めなかった用語集は、設定画面を開き、行の表の代わりに読めなかったことと理由を出す。行を足すボタンは使えない。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "壊れた": content})
    _click(opened.window, "glossary_pick_1")

    # 検証
    unreadable = find(opened.window, QLabel, "glossary_unreadable")
    assert unreadable.isVisible()
    assert unreadable.text().startswith(f"この用語集の CSV を読めませんでした（{reason}")
    assert unreadable.text().endswith("）。保存しても、この CSV は書き換えません。")
    assert opened.window.findChild(QFrame, "glossary_entries") is None
    assert not find(opened.window, QPushButton, "add_glossary_entry_button").isEnabled()


def test_glossary_unreadable_when_cannot_open(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """開けない CSV（フォルダが置いてある）の理由は「ファイルを開けません（{OS のエラー}）」。"""
    # 準備
    (tmp_path / "壊れた.csv").mkdir()

    # 実行
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "壊れた": None})
    _click(opened.window, "glossary_pick_1")

    # 検証
    text = find(opened.window, QLabel, "glossary_unreadable").text()
    assert text.startswith("この用語集の CSV を読めませんでした（ファイルを開けません（")


def test_glossary_unreadable_when_readable(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """読めた用語集の行の表を出しているときは、読めない用語集の知らせを出さない。"""
    # 実行
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "壊れた": SJIS_CSV})

    # 検証
    assert opened.window.findChild(QLabel, "glossary_unreadable") is None


def test_glossary_unreadable_when_saved(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """読めない用語集も、名前を変える・プリセットの使う用語集に追加する・一覧から消すはできる。保存してもその CSV には触れない。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, {"yogo": CSV_FIVE_ROWS, "壊れた": SJIS_CSV, "予備": CSV_TWO_ROWS})
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QLineEdit, "glossary_name_1").setText("直した名前")
    _add_use(opened.window, "直した名前")
    _click(opened.window, "glossary_remove_2")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved, rows = _saved(opened)
    assert [glossary.name for glossary in saved.glossaries] == ["yogo", "直した名前"]
    assert _saved_presets(opened) == [("既定", ["yogo", "直した名前"])]
    assert rows == {}
    assert (tmp_path / "壊れた.csv").read_bytes() == SJIS_CSV


# === input_checks（用語集） ===


def test_input_check_when_glossary_name_empty(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集の名前が空: 「名前を入れてください。」をその欄の下とエラーの一覧に出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_name_0").setText("   ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _field_errors(opened.window) == ["名前を入れてください。"]
    assert "用語集 1 件目の名前: 名前を入れてください。" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_glossary_name_overlap(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """ほかの用語集と同じ名前: 一覧で後ろにある側の欄の下に「用語集「{名前}」と同じ名前です。別の名前にしてください。」、エラーの一覧には「用語集「{名前}」と同じ名前です」を出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QLineEdit, "glossary_name_1").setText("yogo")
    _click(opened.window, "glossary_pick_0")

    # 実行
    _click(opened.window, "save_button")
    _click(opened.window, "glossary_pick_1")

    # 検証
    assert _field_errors(opened.window) == ["用語集「yogo」と同じ名前です。別の名前にしてください。"]
    assert "用語集 2 件目の名前: 用語集「yogo」と同じ名前です" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_glossary_preset_name_empty(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集のプリセットの名前が空: 「名前を入れてください。」をその欄の下とエラーの一覧に出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    find(opened.window, QLineEdit, "glossary_preset_name_0").setText("   ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _field_errors(opened.window) == ["名前を入れてください。"]
    assert "用語集のプリセット 1 件目の名前: 名前を入れてください。" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_glossary_preset_name_overlap(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """ほかの用語集のプリセットと同じ名前（大文字と小文字は区別する）: 一覧で後ろにある側の欄の下とエラーの一覧に「用語集のプリセット「{名前}」と同じ名前です。別の名前にしてください。」を出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    _click(opened.window, "glossary_preset_pick_1")
    find(opened.window, QLineEdit, "glossary_preset_name_1").setText("既定")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "用語集のプリセット「既定」と同じ名前です。別の名前にしてください。"
    assert _field_errors(opened.window) == [message]
    assert f"用語集のプリセット 2 件目の名前: {message}" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_glossary_preset_name_differs_in_case(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """大文字と小文字だけが違う名前は、重なりにしない。"""
    # 準備
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=[("Meeting", ["yogo"]), ("meeting", ["yogo"])]
    )

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _error_rows(opened.window) == []
    assert _saved_presets(opened) == [("Meeting", ["yogo"]), ("meeting", ["yogo"])]


def test_input_check_when_glossary_preset_name_empty_and_overlap(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """空の名前と重なる名前が同じ保存にあれば、両方をエラーの一覧に出し、重なりの行を押すとそのプリセットの名前の欄へ移る。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=[("既定", ["yogo"])])
    add_preset = find(opened.window, QPushButton, "add_glossary_preset_button")
    add_preset.click()
    find(opened.window, QLineEdit, "glossary_preset_name_1").setText("既定")
    add_preset.click()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    rows = _error_rows(opened.window)
    assert "用語集のプリセット 3 件目の名前: 名前を入れてください。" in rows
    assert (
        "用語集のプリセット 2 件目の名前: 用語集のプリセット「既定」と同じ名前です。別の名前にしてください。"
        in rows
    )
    links = [
        label
        for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "glossary_presets[1].name" in label.text()
    ]
    find(opened.window, QListWidget, "group_menu").setCurrentRow(10)
    links[0].linkActivated.emit("glossary_presets[1].name")
    assert find(opened.window, QListWidget, "group_menu").currentRow() == GLOSSARY_GROUP_ROW
    assert opened.window.focusWidget() is find(opened.window, QLineEdit, "glossary_preset_name_1")


def test_input_check_when_glossary_preset_uses_unknown_glossary(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """一覧に無い用語集の名前を持つプリセットは、画面を開くときに外して出す（保存の確かめは断らない）。"""
    # 実行
    opened = _open_glossaries(
        open_window, tmp_path, TWO_GLOSSARIES, presets=[("既定", ["消した用語集", "yogo"])]
    )
    _click(opened.window, "save_button")

    # 検証
    assert _used_names(opened.window) == ["yogo"]
    assert _saved_presets(opened) == [("既定", ["yogo"])]


def test_input_check_when_glossary_entry_wrong_empty(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """誤変換が空で、同じ行の正しい表記が空でない行: 誤変換の欄の下とエラーの一覧に「誤変換を入れてください。」を出す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_entry_wrong_1").setText("")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _field_errors(opened.window) == ["誤変換を入れてください。"]
    assert "用語集 1 件目の 2 行目の誤変換: 誤変換を入れてください。" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()
    assert find(opened.window, QLineEdit, "glossary_entry_right_1").text() != ""


def test_input_check_when_glossary_entry_right_empty(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """誤変換が入っていて正しい表記が空の行は違反にせず、エラーを出さずに保存して、空のまま書き戻す（誤変換を消す行）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_entry_right_1").setText("")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _field_errors(opened.window) == []
    assert _error_rows(opened.window) == []
    saved, rows = _saved(opened)
    assert saved.glossaries[0].name == "yogo"
    assert [(row.wrong, row.right) for row in rows[tmp_path / "yogo.csv"]][:3] == [
        ("あ", "A"),
        ("い", ""),
        ("う", "C"),
    ]


def test_input_check_when_glossary_entry_in_unused_glossary_or_off_row(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """補正に使わない用語集の行も、オフの行も確かめる。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_entry_wrong_2").setText("")
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QLineEdit, "glossary_entry_wrong_0").setText("")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    rows = _error_rows(opened.window)
    assert "用語集 1 件目の 3 行目の誤変換: 誤変換を入れてください。" in rows
    assert "用語集 2 件目の 1 行目の誤変換: 誤変換を入れてください。" in rows
    assert rows[0] == "保存できませんでした。2 件の欄を直してください。"


def test_input_check_when_glossary_entry_both_empty(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """誤変換と正しい表記が両方空の行は違反にせず、保存で捨てる（足しただけの空の行は CSV の行を変えない）。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    _click(opened.window, "add_glossary_entry_button")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved, rows = _saved(opened)
    assert saved.glossaries[0].name == "yogo"
    assert rows == {}


def test_error_summary_row_action_when_glossary(
    open_window: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集の欄の行を押すと、用語集のまとまりへ切り替えて、その用語集の行の表を出して欄へフォーカスを移す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES)
    find(opened.window, QLineEdit, "glossary_name_0").setText("")
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QLineEdit, "glossary_entry_wrong_1").setText("")
    _click(opened.window, "save_button")
    find(opened.window, QListWidget, "group_menu").setCurrentRow(10)
    links = [
        label for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "href" in label.text()
    ]

    # 実行・検証（1 件目の名前、続けて 2 件目の 2 行目の誤変換）
    links[0].linkActivated.emit("glossaries[0].name")
    assert find(opened.window, QListWidget, "group_menu").currentRow() == GLOSSARY_GROUP_ROW
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「（名前未入力）」の行"
    assert opened.window.focusWidget() is find(opened.window, QLineEdit, "glossary_name_0")
    links[1].linkActivated.emit("glossaries[1].rows[1].wrong")
    assert find(opened.window, QLabel, "glossary_detail_title").text() == "用語集「会議用」の行"
    assert opened.window.focusWidget() is find(opened.window, QLineEdit, "glossary_entry_wrong_1")


# === save_button・reset_button（用語集） ===


def test_save_button_when_glossary_changed(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """用語集の一覧・用語集のプリセット・補正に使うプリセット・行を、保存で settings.toml と CSV へ書く。行を変えた用語集の CSV だけを書き戻しに渡す。"""
    # 準備
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    _click(opened.window, "glossary_pick_1")
    find(opened.window, QCheckBox, "glossary_entry_on_0").click()
    find(opened.window, QRadioButton, "glossary_preset_active_1").click()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved, rows = _saved(opened)
    assert saved.active_glossary_preset == "会議"
    assert saved.active_glossary is None
    assert saved.glossary_path is None
    assert _saved_presets(opened) == TWO_PRESETS
    assert list(rows) == [tmp_path / "会議用.csv"]
    assert [(entry.wrong, entry.enabled) for entry in rows[tmp_path / "会議用.csv"]] == [("か", False), ("き", True)]
    opened.saved.assert_called_once()


def test_reset_dialog_when_glossaries(open_window: Callable[..., Opened], tmp_path: Path) -> None:
    """「既定に戻す」は、用語集の一覧を設定ファイルと同じフォルダの yogo.csv の 1 件に戻し、それを使う「既定」のプリセットに戻す。用語集の CSV は消さず、書き換えない。"""
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings

    # 準備（既定に戻したあとに引き直す一覧は、yogo.csv の 1 件と、それを使う「既定」の 1 件）
    default_glossary = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = _open_glossaries(open_window, tmp_path, TWO_GLOSSARIES, presets=TWO_PRESETS)
    two = opened.deps.list_glossaries.return_value
    opened.deps.list_glossaries.side_effect = [[default_glossary]]
    opened.deps.list_glossary_presets.side_effect = [
        [GlossaryPresetSettings(name="既定", glossaries=["yogo"])]
    ]
    find(opened.window, QRadioButton, "glossary_preset_active_1").click()
    driver = ModalDriver()
    driver.answer("reset_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    assert _glossary_names(opened.window) == ["yogo"]
    assert _preset_names(opened.window) == ["既定"]
    assert len(two) == 2
    opened.deps.save_settings.assert_called_once_with(SETTINGS_MODEL(), {})
    assert (tmp_path / "会議用.csv").read_text(encoding="utf-8") == CSV_TWO_ROWS


# === 表記のヒントのまとまり ===

HINT_GROUP_ROW = 6
"""まとまりのメニューの「表記のヒント」の行。"""

HINT_LIMIT_BYTES = 222
"""有効なヒントの長さの上限（UTF-8 のバイト数）。"""

JAPANESE_CHAR_BYTES = 3
"""日本語 1 文字の UTF-8 のバイト数。"""


def _hint_presets(*presets: tuple[str, list[str], bool]) -> list[Any]:
    """（名前, 語の並び, 有効か）から HintPresetSettings の並びを作る。"""
    from voice_paste.shared.settings import HintPresetSettings

    return [HintPresetSettings(name=name, words=words, enabled=enabled) for name, words, enabled in presets]


def _open_hints(open_window: Callable[..., Opened], *presets: tuple[str, list[str], bool]) -> Opened:
    """表記のヒントのプリセットを持つ設定で設定画面を開いて、表記のヒントのまとまりを選ぶ。"""
    opened = open_window(SETTINGS_MODEL(hint_presets=_hint_presets(*presets)))
    find(opened.window, QListWidget, "group_menu").setCurrentRow(HINT_GROUP_ROW)
    return opened


def _hint_length_texts(window: QWidget) -> list[str]:
    """有効なヒントの長さの行（hint_length）に出ている文字を並べる。"""
    return [label.text() for label in find(window, QWidget, "hint_length").findChildren(QLabel)]


def _hint_words(window: QWidget) -> list[str]:
    """画面に出ている語の欄の文字を、プリセットと語の順で並べる。"""
    return [edit.text() for edit in _widgets(window, QLineEdit, "hint_word_") if edit.objectName()[len("hint_word_")].isdigit()]


def _hint_over_message(length: int) -> str:
    """上限を超えたときの欄の下の文言（保存を押した後）。"""
    return f"有効なヒントが長すぎます（{length} / {HINT_LIMIT_BYTES} バイト）。語を減らすか、プリセットを無効にしてください。"


# === hint_intro・hint_notes・hint_preset_add ===


def test_hint_group_when_visible(open_window: Callable[..., Opened]) -> None:
    """表記のヒントのまとまりを選ぶと、説明・有効なヒントの長さ・案内・足すボタン・補足が出る。ほかのまとまりを選ぶと出ない。"""
    # 準備
    opened = open_window()

    # 実行・検証（選ぶ前は出ない）
    assert not find(opened.window, QLabel, "hint_intro").isVisible()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(HINT_GROUP_ROW)
    assert find(opened.window, QLabel, "hint_intro").isVisible()
    assert find(opened.window, QLabel, "hint_intro").text() == (
        "間違えやすい語の正しい表記を並べる。文字起こしへの指示としては効かない。"
    )
    assert find(opened.window, QWidget, "hint_length").isVisible()
    assert find(opened.window, QPushButton, "hint_preset_add").text() == "プリセットを足す"
    notes = find(opened.window, QLabel, "hint_notes")
    assert notes.isVisible()
    assert "句読点が付く・改行がまとまる・口癖が一部消える" in notes.text()
    assert "TypeScript がタイプスクリプトになったら「TypeScript」を足す" in notes.text()


# === hint_preset_empty ===


def test_hint_preset_empty_when_no_presets(open_window: Callable[..., Opened]) -> None:
    """プリセットが 1 件も無いときは、無い間はヒントを渡さないことを伝える案内を出し、長さは 0。"""
    # 実行
    opened = _open_hints(open_window)

    # 検証
    empty = find(opened.window, QLabel, "hint_preset_empty")
    assert empty.isVisible()
    assert empty.text() == "ヒントのプリセットはまだありません。無い間は、ヒントを渡さずに文字を起こします。"
    assert "0 / 222 バイト" in _hint_length_texts(opened.window)


def test_hint_preset_empty_when_presets_exist(open_window: Callable[..., Opened]) -> None:
    """プリセットがあるときは案内を出さない。"""
    # 実行
    opened = _open_hints(open_window, ("開発", ["voice-paste"], True))

    # 検証
    assert not find(opened.window, QLabel, "hint_preset_empty").isVisible()


# === hint_preset_list・hint_preset_name_{n}・hint_word_{n}_{m} ===


def test_hint_preset_list_initial_value(open_window: Callable[..., Opened]) -> None:
    """settings.toml の hint_presets の並びのとおりに、名前・語・有効かを出す。"""
    # 実行
    opened = _open_hints(open_window, ("開発", ["voice-paste", "Whisper"], True), ("会議", ["議事録"], False))

    # 検証
    window = opened.window
    assert [edit.text() for edit in _widgets(window, QLineEdit, "hint_preset_name_")] == ["開発", "会議"]
    assert _hint_words(window) == ["voice-paste", "Whisper", "議事録"]
    assert [box.isChecked() for box in _widgets(window, QCheckBox, "hint_preset_enabled_")] == [True, False]
    assert find(window, QLineEdit, "hint_word_0_1").accessibleName() == "2 つ目の語"


def test_hint_preset_list_when_not_in_settings_toml(open_window: Callable[..., Opened]) -> None:
    """hint_presets のキーが無い今の設定でも開け、プリセットは空。"""
    # 実行
    opened = _open_hints(open_window)

    # 検証
    assert _widgets(opened.window, QLineEdit, "hint_preset_name_") == []


# === hint_preset_enabled_{n} ===


def test_hint_preset_enabled_initial_value(open_window: Callable[..., Opened]) -> None:
    """切り替えの右に今の状態を文字で出し、読み上げの名前は「{名前}を有効にする」（名前が空なら「プリセット {何件目か} 件目を有効にする」）。"""
    # 実行
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], False))
    find(opened.window, QLineEdit, "hint_preset_name_1").setText("")

    # 検証
    boxes = _widgets(opened.window, QCheckBox, "hint_preset_enabled_")
    assert [box.text() for box in boxes] == ["有効", "無効"]
    assert [box.accessibleName() for box in boxes] == ["開発を有効にする", "プリセット 2 件目を有効にする"]


def test_hint_preset_enabled_action(open_window: Callable[..., Opened]) -> None:
    """切り替えると文字が替わり、無効のプリセットの語は有効なヒントの長さに数えない。無効の語の欄は薄くして取り消し線を引く（編集はできる）。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["abc"], True), ("会議", ["議事録"], False))
    window = opened.window
    disabled_word = find(window, QLineEdit, "hint_word_1_0")
    assert disabled_word.font().strikeOut()
    assert disabled_word.graphicsEffect() is not None
    assert "3 / 222 バイト" in _hint_length_texts(window)

    # 実行
    find(window, QCheckBox, "hint_preset_enabled_1").click()

    # 検証
    assert find(window, QCheckBox, "hint_preset_enabled_1").text() == "有効"
    assert not disabled_word.font().strikeOut()
    assert disabled_word.graphicsEffect() is None
    assert "15 / 222 バイト" in _hint_length_texts(window)
    assert disabled_word.isEnabled()


def test_hint_preset_enabled_when_saved(open_window: Callable[..., Opened]) -> None:
    """保存で hint_presets の enabled に書く。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], False))
    find(opened.window, QCheckBox, "hint_preset_enabled_0").click()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved = opened.deps.save_settings.call_args.args[0]
    assert [(preset.name, preset.enabled) for preset in saved.hint_presets] == [("開発", False), ("会議", False)]


# === hint_length ===


def test_hint_length_when_words_changed(open_window: Callable[..., Opened]) -> None:
    """語を書き換える・足す・消すたびに、有効なプリセットの語を読点でつないだ長さを数え直す（語の間の読点も数える）。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["abc"], True))
    window = opened.window
    assert "3 / 222 バイト" in _hint_length_texts(window)

    # 実行・検証（語を足して「de」を入れると「abc、de」の 8 バイト。読点は 3 バイト）
    _click(window, "hint_word_add_0")
    find(window, QLineEdit, "hint_word_0_1").setText("de")
    assert "8 / 222 バイト" in _hint_length_texts(window)
    find(window, QLineEdit, "hint_word_0_0").setText("あい")
    assert "11 / 222 バイト" in _hint_length_texts(window)
    _click(window, "hint_word_remove_0_1")
    assert "6 / 222 バイト" in _hint_length_texts(window)


def test_hint_length_when_at_limit(open_window: Callable[..., Opened]) -> None:
    """上限ちょうど（222 バイト）は超過の文字を添えず、保存できる。"""
    # 準備
    word = "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES)
    opened = _open_hints(open_window, ("開発", [word], True))

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert "222 / 222 バイト" in _hint_length_texts(opened.window)
    opened.deps.save_settings.assert_called_once()


def test_hint_length_when_over(open_window: Callable[..., Opened]) -> None:
    """上限を超えたら、超過したバイト数を文字で添える（色だけで伝えない）。入力の途中でエラー文は出さない。"""
    # 準備
    word = "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES + 1)
    opened = _open_hints(open_window, ("開発", ["a"], True))

    # 実行
    find(opened.window, QLineEdit, "hint_word_0_0").setText(word)

    # 検証
    assert "225 / 222 バイト（3 バイト超過）" in _hint_length_texts(opened.window)
    assert not find(opened.window, QFrame, "error_summary").isVisible()
    assert not find(opened.window, QLabel, "hint_length_error").isVisible()


def test_hint_length_when_words_have_surrounding_spaces(open_window: Callable[..., Opened]) -> None:
    """語の前後の空白は、保存の確かめと同じく除いて数える（欄の文字をそのまま数えて、保存の判定とずれない）。"""
    # 準備（語の前後に空白を足して、そのまま数えると 222 バイトを超えるが、除くと上限ちょうど）
    word = "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES)
    opened = _open_hints(open_window, ("開発", [word], True))
    edit = find(opened.window, QLineEdit, "hint_word_0_0")

    # 実行
    edit.setText(f"  {word}  ")

    # 検証（画面は上限ちょうど。保存も通り、書く語は空白を除いたもの）
    assert "222 / 222 バイト" in _hint_length_texts(opened.window)
    _click(opened.window, "save_button")
    saved = opened.deps.save_settings.call_args.args[0]
    assert saved.hint_presets[0].words == [word]


# === hint_preset_size_{n} ===


def test_hint_preset_size_initial_value(open_window: Callable[..., Opened]) -> None:
    """プリセットごとに「{語の数} 語・{長さ} バイト」を出す（そのプリセットの語だけを読点でつないだ長さ。無効のプリセットでも出す）。"""
    # 実行
    opened = _open_hints(open_window, ("開発", ["abc", "de"], True), ("会議", ["議事録"], False))

    # 検証
    assert find(opened.window, QLabel, "hint_preset_size_0").text() == "2 語・8 バイト"
    assert find(opened.window, QLabel, "hint_preset_size_1").text() == "1 語・9 バイト"


def test_hint_preset_size_action(open_window: Callable[..., Opened]) -> None:
    """語を足す・書き換える・消すたびに数え直す。語の前後の空白は除いて数える。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["abc"], True))
    window = opened.window

    # 実行・検証
    _click(window, "hint_word_add_0")
    find(window, QLineEdit, "hint_word_0_1").setText("  de  ")
    assert find(window, QLabel, "hint_preset_size_0").text() == "2 語・8 バイト"
    _click(window, "hint_word_remove_0_0")
    assert find(window, QLabel, "hint_preset_size_0").text() == "1 語・2 バイト"


# === hint_preset_name_{n} ===


def test_hint_preset_name_action(open_window: Callable[..., Opened]) -> None:
    """入れた名前をまとまりの頭にも出す（空なら「（名前未入力）」、長ければ末尾を省く）。操作の読み上げの名前も入れた名前に合わせる。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    window = opened.window
    name_edit = find(window, QLineEdit, "hint_preset_name_0")

    # 実行・検証
    name_edit.setText("会議")
    assert find(window, QCheckBox, "hint_preset_enabled_0").accessibleName() == "会議を有効にする"
    assert find(window, QPushButton, "hint_preset_remove_0").accessibleName() == "会議を消す"
    assert "会議" in [label.text() for label in window.findChildren(QLabel)]
    name_edit.setText("")
    assert "（名前未入力）" in [label.text() for label in window.findChildren(QLabel)]
    assert find(window, QPushButton, "hint_preset_remove_0").accessibleName() == "プリセット 1 件目を消す"
    name_edit.setText("あ" * 30)
    assert ("あ" * 19 + "…") in [label.text() for label in window.findChildren(QLabel)]
    assert name_edit.text() == "あ" * 30


# === hint_preset_up_{n}・hint_preset_down_{n} ===


def test_hint_preset_move_action(open_window: Callable[..., Opened]) -> None:
    """上へ・下へで並びを入れ替える（語をつなぐ順もこの順）。先頭の上へと末尾の下へは押せない。"""
    # 準備
    opened = _open_hints(open_window, ("A", ["a"], True), ("B", ["b"], True), ("C", ["c"], True))
    window = opened.window
    assert [find(window, QPushButton, f"hint_preset_up_{n}").isEnabled() for n in range(3)] == [False, True, True]
    assert [find(window, QPushButton, f"hint_preset_down_{n}").isEnabled() for n in range(3)] == [True, True, False]

    # 実行（A の「下へ」、続けて C の「上へ」）
    _click(window, "hint_preset_down_0")
    _click(window, "hint_preset_up_2")

    # 検証
    assert [edit.text() for edit in _widgets(window, QLineEdit, "hint_preset_name_")] == ["B", "C", "A"]
    _click(window, "save_button")
    saved = opened.deps.save_settings.call_args.args[0]
    assert [preset.name for preset in saved.hint_presets] == ["B", "C", "A"]


# === hint_preset_remove_{n} ===


def test_hint_preset_remove_action(open_window: Callable[..., Opened]) -> None:
    """消すと一覧から外して長さを数え直す。保存するまで settings.toml には書かず、キャンセルで戻せる。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["abc"], True), ("会議", ["de"], True))
    window = opened.window

    # 実行
    _click(window, "hint_preset_remove_0")

    # 検証
    assert [edit.text() for edit in _widgets(window, QLineEdit, "hint_preset_name_")] == ["会議"]
    assert "2 / 222 バイト" in _hint_length_texts(window)
    opened.deps.save_settings.assert_not_called()
    assert find(window, QLabel, "hint_preset_size_0").text() == "1 語・2 バイト"


def test_hint_preset_remove_when_last(open_window: Callable[..., Opened]) -> None:
    """最後の 1 件を消すと案内が出て、保存すると hint_presets は空になる。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["abc"], True))

    # 実行
    _click(opened.window, "hint_preset_remove_0")
    _click(opened.window, "save_button")

    # 検証
    assert opened.deps.save_settings.call_args.args[0].hint_presets == []


# === hint_preset_add ===


def test_hint_preset_add_action(open_window: Callable[..., Opened]) -> None:
    """名前と語が空で有効のプリセットを末尾に足し、名前の欄へフォーカスを移す。足して語を入れただけで効く。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    window = opened.window

    # 実行
    _click(window, "hint_preset_add")

    # 検証
    assert [edit.text() for edit in _widgets(window, QLineEdit, "hint_preset_name_")] == ["開発", ""]
    assert find(window, QCheckBox, "hint_preset_enabled_1").isChecked()
    assert find(window, QCheckBox, "hint_preset_enabled_1").text() == "有効"
    assert window.focusWidget() is find(window, QLineEdit, "hint_preset_name_1")
    assert not find(window, QLabel, "hint_preset_empty").isVisible()


def test_hint_preset_add_when_saved(open_window: Callable[..., Opened]) -> None:
    """足した名前と語は、保存で hint_presets に書く。"""
    # 準備
    opened = _open_hints(open_window)
    _click(opened.window, "hint_preset_add")
    find(opened.window, QLineEdit, "hint_preset_name_0").setText("開発")
    _click(opened.window, "hint_word_add_0")
    find(opened.window, QLineEdit, "hint_word_0_0").setText("voice-paste")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved = opened.deps.save_settings.call_args.args[0]
    assert [(preset.name, preset.words, preset.enabled) for preset in saved.hint_presets] == [
        ("開発", ["voice-paste"], True)
    ]
    opened.saved.assert_called_once()


# === hint_words_empty_{n}・hint_word_add_{n}・hint_word_remove_{n}_{m} ===


def test_hint_words_empty_when_no_words(open_window: Callable[..., Opened]) -> None:
    """語が 1 つも無いプリセットは、語の欄の代わりに語が無いことを伝える。語を足すと消える。"""
    # 準備
    opened = _open_hints(open_window, ("開発", [], True))
    window = opened.window
    empty = find(window, QLabel, "hint_words_empty_0")
    assert empty.isVisible()
    assert empty.text() == "このプリセットにはまだ語がありません。"

    # 実行
    _click(window, "hint_word_add_0")

    # 検証
    assert window.findChild(QLabel, "hint_words_empty_0") is None
    assert window.focusWidget() is find(window, QLineEdit, "hint_word_0_0")


def test_hint_word_add_action(open_window: Callable[..., Opened]) -> None:
    """空の語の欄をそのプリセットの語の末尾に足し、その欄へフォーカスを移す。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))

    # 実行
    _click(opened.window, "hint_word_add_1")

    # 検証
    assert _hint_words(opened.window) == ["a", "b", ""]
    assert opened.window.focusWidget() is find(opened.window, QLineEdit, "hint_word_1_1")


def test_hint_word_remove_action(open_window: Callable[..., Opened]) -> None:
    """語を 1 つ消す。読み上げの名前は「{何つ目か} つ目の語を消す」。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a", "b", "c"], True))
    assert find(opened.window, QPushButton, "hint_word_remove_0_1").accessibleName() == "2 つ目の語を消す"

    # 実行
    _click(opened.window, "hint_word_remove_0_1")

    # 検証
    assert _hint_words(opened.window) == ["a", "c"]
    opened.deps.save_settings.assert_not_called()


def test_hint_words_when_narrow_window(open_window: Callable[..., Opened]) -> None:
    """語の欄は入力と消すボタンの組を 2 列に並べ、左から右、上から下が語の順になる。幅が組 2 つに足りなければ 1 列に積む。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a", "b", "c", "d"], True))
    window = opened.window
    panel = find(window, QWidget, "hint_preset_panel")

    # 実行・検証（広いとき）
    panel.setFixedWidth(900)
    QTest.qWait(0)
    edits = [find(window, QLineEdit, f"hint_word_0_{m}") for m in range(4)]
    tops = [_top_of(edit, window) for edit in edits]
    lefts = [_left_of(edit, window) for edit in edits]
    assert tops[0] == tops[1] < tops[2] == tops[3]
    assert lefts[0] == lefts[2] < lefts[1] == lefts[3]

    # 実行・検証（狭いとき）
    panel.setFixedWidth(300)
    QTest.qWait(0)
    lefts = [_left_of(edit, window) for edit in edits]
    tops = [_top_of(edit, window) for edit in edits]
    assert len(set(lefts)) == 1
    assert tops == sorted(tops)
    assert len(set(tops)) == 4


# === input_checks（表記のヒント） ===


def test_input_check_when_hint_too_long(open_window: Callable[..., Opened]) -> None:
    """有効なヒントが 222 バイトを超える: 長さの行の下とエラーの一覧に出す。無効のプリセットの語は数えない。"""
    # 準備
    word = "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES + 1)
    opened = _open_hints(open_window, ("開発", ["a"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText(word)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = _hint_over_message(225)
    assert find(opened.window, QLabel, "hint_length_error").text() == message
    assert find(opened.window, QLabel, "hint_length_error").isVisible()
    assert f"有効なヒントの長さ: {message}" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_hint_too_long_in_disabled_preset(open_window: Callable[..., Opened]) -> None:
    """無効のプリセットの語は長さに数えないので、長くても保存できる。"""
    # 準備
    word = "あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES + 10)
    opened = _open_hints(open_window, ("開発", ["abc"], True), ("会議", [word], False))

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_called_once()


def test_input_check_when_hint_word_empty(open_window: Callable[..., Opened]) -> None:
    """空の語（前後の空白を除いて）: 「語を入れるか、この欄を消してください。」をその欄の下とエラーの一覧に出す。無効のプリセットの語も確かめる。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a", "b"], False))
    find(opened.window, QLineEdit, "hint_word_0_1").setText("  ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "語を入れるか、この欄を消してください。"
    assert message in _field_errors(opened.window)
    assert f"プリセット 1 件目の 2 つ目の語: {message}" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


@pytest.mark.parametrize("word", ["A、B", "C。", "D\nE"])
def test_input_check_when_hint_word_has_separator(open_window: Callable[..., Opened], word: str) -> None:
    """読点（、）・句点（。）・改行を含む語: 「読点（、）・句点（。）・改行は入れられません。語を分けて足してください。」を出す。"""
    # 準備（改行は 1 行の欄に入れられないため、欄の文字を直接差し替える）
    opened = _open_hints(open_window, ("開発", ["a"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText(word)

    # 実行
    _click(opened.window, "save_button")

    # 検証
    message = "読点（、）・句点（。）・改行は入れられません。語を分けて足してください。"
    assert message in _field_errors(opened.window)
    assert f"プリセット 1 件目の 1 つ目の語: {message}" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_hint_preset_name_empty(open_window: Callable[..., Opened]) -> None:
    """名前が空（前後の空白を除いて）: 「名前を入れてください。」をその欄の下とエラーの一覧に出す。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    find(opened.window, QLineEdit, "hint_preset_name_0").setText("   ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert "名前を入れてください。" in _field_errors(opened.window)
    assert "プリセット 1 件目の名前: 名前を入れてください。" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_hint_preset_name_overlap(open_window: Callable[..., Opened]) -> None:
    """ほかのヒントのプリセットと同じ名前（前後の空白を除いて比べる）: 一覧で後ろにある側の欄の下に「別の名前にしてください。」まで、エラーの一覧にはそれを添えずに出す。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    find(opened.window, QLineEdit, "hint_preset_name_1").setText(" 開発 ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert "プリセット「開発」と同じ名前です。別の名前にしてください。" in _field_errors(opened.window)
    assert "プリセット 2 件目の名前: プリセット「開発」と同じ名前です" in _error_rows(opened.window)
    opened.deps.save_settings.assert_not_called()


def test_input_check_when_hint_errors_counted(open_window: Callable[..., Opened]) -> None:
    """エラーの一覧の見出しは、直す欄の件数を数える。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a", "x"], True), ("会議", ["b"], True))
    find(opened.window, QLineEdit, "hint_word_0_1").setText("")
    find(opened.window, QLineEdit, "hint_preset_name_1").setText("")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert _error_rows(opened.window)[0] == "保存できませんでした。2 件の欄を直してください。"


def test_input_check_when_hint_errors_cleared(open_window: Callable[..., Opened]) -> None:
    """直して保存し直すと、前のエラーは消える。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a", "x"], True))
    find(opened.window, QLineEdit, "hint_word_0_1").setText("")
    _click(opened.window, "save_button")
    assert _field_errors(opened.window)

    # 実行
    find(opened.window, QLineEdit, "hint_word_0_1").setText("b")
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_called_once()


def test_error_summary_row_action_when_hint_length(open_window: Callable[..., Opened]) -> None:
    """有効なヒントの長さの行を押すと、表記のヒントのまとまりへ切り替えて長さの行へフォーカスを移す。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText("あ" * (HINT_LIMIT_BYTES // JAPANESE_CHAR_BYTES + 1))
    _click(opened.window, "save_button")
    find(opened.window, QListWidget, "group_menu").setCurrentRow(10)
    link = next(
        label for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "href" in label.text()
    )

    # 実行
    link.linkActivated.emit("hint_presets")

    # 検証
    assert find(opened.window, QListWidget, "group_menu").currentRow() == HINT_GROUP_ROW
    assert opened.window.focusWidget() is find(opened.window, QWidget, "hint_length")


def test_error_summary_row_action_when_hint_word(open_window: Callable[..., Opened]) -> None:
    """語の欄の行を押すと、表記のヒントのまとまりへ切り替えて、その語の欄へフォーカスを移す。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a", "x"], True))
    find(opened.window, QLineEdit, "hint_word_0_1").setText("")
    _click(opened.window, "save_button")
    find(opened.window, QListWidget, "group_menu").setCurrentRow(10)
    link = next(
        label for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "href" in label.text()
    )

    # 実行
    link.linkActivated.emit("hint_presets[0].words[1]")

    # 検証
    assert find(opened.window, QListWidget, "group_menu").currentRow() == HINT_GROUP_ROW
    assert opened.window.focusWidget() is find(opened.window, QLineEdit, "hint_word_0_1")


# === save_button・reset_button・キャンセル（表記のヒント） ===


def test_save_button_when_hint_changed(open_window: Callable[..., Opened]) -> None:
    """表記のヒントを変えて保存すると、再起動せずに効く値（immediate）として書き、窓を開いたまま保存した知らせを出す。「再起動で反映」の知らせは出さない。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText("b")
    assert not find(opened.window, QLabel, "restart_notice").isVisible()

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved = opened.deps.save_settings.call_args.args[0]
    assert saved.hint_presets[0].words == ["b"]
    opened.saved.assert_called_once()
    opened.closed.assert_not_called()
    assert find(opened.window, QLabel, "saved_notice").text() == "保存しました。"
    assert not find(opened.window, QLabel, "restart_notice").isVisible()


def test_cancel_button_when_hint_changed(open_window: Callable[..., Opened]) -> None:
    """表記のヒントを変えてキャンセルすると、変えた値を捨てる確認を出し、捨てると settings.toml には書かない。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText("b")
    driver = ModalDriver()
    driver.answer("discard_button")

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    opened.deps.save_settings.assert_not_called()
    opened.closed.assert_called_once()


def test_reset_dialog_when_hint_presets(open_window: Callable[..., Opened]) -> None:
    """「既定に戻す」は、表記のヒントのプリセットを空にする。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    driver = ModalDriver()
    driver.answer("reset_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    opened.deps.save_settings.assert_called_once_with(SETTINGS_MODEL(), {})
    assert _widgets(opened.window, QLineEdit, "hint_preset_name_") == []
    assert len(_widgets(opened.window, QLabel, "hint_preset_empty")) == 1


# === discard_body（表記のヒントの変更の件数） ===


def test_discard_body_when_hint_preset_added(open_window: Callable[..., Opened]) -> None:
    """プリセットを 1 つ足すと、変えた件数は 1 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True))
    _click(opened.window, "hint_preset_add")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_hint_preset_removed(open_window: Callable[..., Opened]) -> None:
    """プリセットを 1 つ消すと、変えた件数は 1 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    _click(opened.window, "hint_preset_remove_0")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_hint_preset_renamed_twice(open_window: Callable[..., Opened]) -> None:
    """1 つのプリセットの名前を 2 回変えても、変えた件数は 1 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    find(opened.window, QLineEdit, "hint_preset_name_0").setText("改名1")
    find(opened.window, QLineEdit, "hint_preset_name_0").setText("改名2")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_hint_word_changed(open_window: Callable[..., Opened]) -> None:
    """プリセットの語を変えると、変えた件数は 1 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText("変えた")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_hint_preset_toggled(open_window: Callable[..., Opened]) -> None:
    """プリセットの有効を切り替えると、変えた件数は 1 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    find(opened.window, QCheckBox, "hint_preset_enabled_0").click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_hint_preset_moved(open_window: Callable[..., Opened]) -> None:
    """プリセットを並べ替えると、変えた件数は並べ替えの 1 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    _click(opened.window, "hint_preset_down_0")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_two_hint_presets_changed(open_window: Callable[..., Opened]) -> None:
    """2 つのプリセットを変えると、変えた件数は 2 件。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText("変えた1")
    find(opened.window, QLineEdit, "hint_preset_name_1").setText("変えた2")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(2)


def test_discard_body_when_hint_preset_removed_from_middle(
    open_window: Callable[..., Opened],
) -> None:
    """途中のプリセットを消すと、変えた件数は消した 1 件（残ったプリセットの順は並べ替えに数えない）。"""
    # 準備
    opened = _open_hints(open_window, ("A", ["a"], True), ("B", ["b"], True), ("C", ["c"], True))
    _click(opened.window, "hint_preset_remove_1")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_hint_preset_moved_after_saved(
    open_window: Callable[..., Opened],
) -> None:
    """保存してから並べ替えると、変えた件数は並べ替えの 1 件（保存で変えた分は数えない）。"""
    # 準備
    opened = _open_hints(open_window, ("開発", ["a"], True), ("会議", ["b"], True))
    find(opened.window, QLineEdit, "hint_word_0_0").setText("変えた")
    _click(opened.window, "save_button")
    _click(opened.window, "hint_preset_down_0")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


# === ハルシネーションのまとまり ===

EDGE_GROUP_ROW = 8
"""まとまりのメニューの「ハルシネーション」の行。"""

NARROW_PANEL_WIDTH_PX = 300
"""文言の一覧が 1 行を 2 段に組む幅。"""

WIDE_PANEL_WIDTH_PX = 900
"""文言の一覧が 1 行を 1 段に組む幅。"""

DROP_MARGIN_PX = 10
"""つまみを離す位置を、行の中心から上下へずらす距離。"""


def _edge_phrases(*phrases: tuple[str, str]) -> list[Any]:
    """（文言, 位置）から EdgePhraseSettings の並びを作る。"""
    from voice_paste.shared.settings import EdgePhraseSettings

    return [EdgePhraseSettings(text=text, position=position) for text, position in phrases]


def _open_edge(open_window: Callable[..., Opened], *phrases: tuple[str, str]) -> Opened:
    """文頭・文末から消す文言を持つ設定で設定画面を開いて、ハルシネーションのまとまりを選ぶ。"""
    opened = open_window(SETTINGS_MODEL(edge_phrases=_edge_phrases(*phrases)))
    find(opened.window, QListWidget, "group_menu").setCurrentRow(EDGE_GROUP_ROW)
    return opened


def _edge_texts(window: QWidget) -> list[str]:
    """画面に出ている文言の欄の文字を、行の順で並べる。"""
    return [edit.text() for edit in _widgets(window, QLineEdit, "edge_phrase_text_")]


def _edge_positions(window: QWidget) -> list[str]:
    """画面に出ている位置の選択の今の表示を、行の順で並べる。"""
    return [box.currentText() for box in _widgets(window, QComboBox, "edge_phrase_position_")]


def _drag_grip(window: QWidget, number: int, global_y: int) -> None:
    """number 行目のつまみを掴んで、画面上の縦の位置 global_y で離す。"""
    grip = find(window, QLabel, f"edge_phrase_grip_{number}")
    QTest.mousePress(grip, Qt.MouseButton.LeftButton)
    release_at = grip.mapFromGlobal(QPoint(grip.mapToGlobal(QPoint(0, 0)).x(), global_y))
    QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=release_at)


def _row_center_y(window: QWidget, number: int) -> int:
    """number 行目の縦の中心の、画面上の位置を返す。"""
    edit = find(window, QLineEdit, f"edge_phrase_text_{number}")
    return edit.mapToGlobal(QPoint(0, edit.height() // 2)).y()


def _alt_key(window: QWidget, number: int, key_code: Qt.Key) -> None:
    """number 行目の文言の欄に Alt+キーを押す。"""
    edit = find(window, QLineEdit, f"edge_phrase_text_{number}")
    edit.setFocus()
    QTest.keyClick(edit, key_code, Qt.KeyboardModifier.AltModifier)


# === edge_phrase_intro・edge_phrase_legend・add_edge_phrase_button ===


def test_edge_phrase_group_when_visible(open_window: Callable[..., Opened]) -> None:
    """ハルシネーションのまとまりを選ぶと、説明・凡例・行を足すボタンが出る。ほかのまとまりを選ぶと出ない。"""
    # 準備
    opened = open_window()

    # 実行・検証（選ぶ前は出ない）
    assert not find(opened.window, QLabel, "edge_phrase_intro").isVisible()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(EDGE_GROUP_ROW)
    assert find(opened.window, QLabel, "edge_phrase_intro").text() == (
        "文字起こしが文頭・文末に足す、話していない文言を消す。"
    )
    assert find(opened.window, QLabel, "edge_phrase_legend").text() == (
        "上の行から順に当てる。* は任意の文字列に一致する。行は左端を掴むか、Alt+↑ / Alt+↓ で動かす。"
    )
    assert find(opened.window, QLabel, "edge_phrase_legend").isVisible()
    assert find(opened.window, QPushButton, "add_edge_phrase_button").text() == "行を足す"
    find(opened.window, QListWidget, "group_menu").setCurrentRow(0)
    assert not find(opened.window, QLabel, "edge_phrase_intro").isVisible()


# === edge_phrase_list ===


def test_edge_phrase_list_initial_value(open_window: Callable[..., Opened]) -> None:
    """settings.toml の edge_phrases の値と並びのとおりに、文言と位置を出す。読み上げの表の名前は「文頭・文末から消す文言（上の行から順に当てる）」。"""
    # 実行
    opened = _open_edge(open_window, ("えーと", "start"), ("ありがとうございました", "both"), ("字幕*", "end"))

    # 検証
    window = opened.window
    assert _edge_texts(window) == ["えーと", "ありがとうございました", "字幕*"]
    assert _edge_positions(window) == ["文頭", "両方", "文末"]
    assert find(window, QWidget, "edge_phrase_list").accessibleName() == "文頭・文末から消す文言（上の行から順に当てる）"
    assert find(window, QLineEdit, "edge_phrase_text_1").accessibleName() == "2 行目の文言"
    assert find(window, QComboBox, "edge_phrase_position_1").accessibleName() == "2 行目の位置"
    assert not find(window, QLabel, "edge_phrase_empty").isVisible()


def test_edge_phrase_list_when_not_in_settings_toml(open_window: Callable[..., Opened]) -> None:
    """edge_phrases のキーが無い今の設定では、既定の 3 行（全て文末）を出す。"""
    # 実行
    opened = open_window()
    find(opened.window, QListWidget, "group_menu").setCurrentRow(EDGE_GROUP_ROW)

    # 検証
    assert _edge_texts(opened.window) == ["チャンネル登録*", "ご視聴ありがとうございました", "ありがとうございました"]
    assert _edge_positions(opened.window) == ["文末", "文末", "文末"]


def test_edge_phrase_list_when_narrow_window(open_window: Callable[..., Opened]) -> None:
    """幅が広いときは 1 行を 1 段に組んで列の見出しを出し、狭いときは 2 段（上に文言の欄、下に位置と消すボタン）に組んで見出しを隠す。"""
    # 準備
    opened = _open_edge(open_window, ("えーと", "start"), ("字幕*", "end"))
    window = opened.window
    panel = find(window, QWidget, "edge_phrase_panel")
    header = find(window, QWidget, "edge_phrase_header")

    # 実行・検証（広いとき）
    panel.setFixedWidth(WIDE_PANEL_WIDTH_PX)
    QTest.qWait(0)
    text_edit = find(window, QLineEdit, "edge_phrase_text_0")
    position_box = find(window, QComboBox, "edge_phrase_position_0")
    assert header.isVisible()
    assert [label.text() for label in header.findChildren(QLabel)] == ["文言", "位置"]
    assert abs(_top_of(text_edit, window) - _top_of(position_box, window)) <= position_box.height()
    assert _left_of(text_edit, window) < _left_of(position_box, window)

    # 実行・検証（狭いとき）
    panel.setFixedWidth(NARROW_PANEL_WIDTH_PX)
    QTest.qWait(0)
    assert not header.isVisible()
    assert _top_of(text_edit, window) < _top_of(position_box, window)
    assert _left_of(text_edit, window) <= _left_of(position_box, window)


# === edge_phrase_empty ===


def test_edge_phrase_empty_when_no_phrases(open_window: Callable[..., Opened]) -> None:
    """行が 1 つも無いときは、一覧の代わりに、無い間は何も消さないことを伝える文を出す。"""
    # 実行
    opened = _open_edge(open_window)

    # 検証
    empty = find(opened.window, QLabel, "edge_phrase_empty")
    assert empty.isVisible()
    assert empty.text() == "消す文言はまだありません。無い間は、文頭・文末から何も消しません。"
    assert not find(opened.window, QWidget, "edge_phrase_list").isVisible()


def test_edge_phrase_empty_when_phrases_exist(open_window: Callable[..., Opened]) -> None:
    """行があるときは、空の文を出さない。"""
    # 実行
    opened = _open_edge(open_window, ("えーと", "start"))

    # 検証
    assert not find(opened.window, QLabel, "edge_phrase_empty").isVisible()
    assert find(opened.window, QWidget, "edge_phrase_list").isVisible()


# === edge_phrase_grip_{n} ===


def test_edge_phrase_grip_does_not_take_focus(open_window: Callable[..., Opened]) -> None:
    """つまみはフォーカスを受けず、マウスを重ねるとツールチップ「掴んで動かす」を出す。"""
    # 実行
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"))

    # 検証
    grip = find(opened.window, QLabel, "edge_phrase_grip_0")
    assert grip.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert grip.toolTip() == "掴んで動かす"


def test_edge_phrase_grip_action_when_dropped_below(open_window: Callable[..., Opened]) -> None:
    """つまみを掴んで下の行より下で離すと、その位置へ行が動く。保存するまで settings.toml には書かない。"""
    # 準備
    opened = _open_edge(open_window, ("A", "start"), ("B", "end"), ("C", "both"))
    window = opened.window

    # 実行（1 行目を、3 行目の中心より下で離す）
    _drag_grip(window, 0, _row_center_y(window, 2) + DROP_MARGIN_PX)

    # 検証
    assert _edge_texts(window) == ["B", "C", "A"]
    assert _edge_positions(window) == ["文末", "両方", "文頭"]
    opened.deps.save_settings.assert_not_called()


def test_edge_phrase_grip_action_when_dropped_above(open_window: Callable[..., Opened]) -> None:
    """3 行目のつまみを、1 行目の中心より上で離すと、先頭へ動く。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"), ("C", "end"))
    window = opened.window

    # 実行
    _drag_grip(window, 2, _row_center_y(window, 0) - DROP_MARGIN_PX)

    # 検証
    assert _edge_texts(window) == ["C", "A", "B"]


def test_edge_phrase_grip_action_when_dropped_in_between(open_window: Callable[..., Opened]) -> None:
    """1 行目のつまみを、2 行目と 3 行目の間で離すと、2 行目の次へ動く。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"), ("C", "end"))
    window = opened.window
    between = (_row_center_y(window, 1) + _row_center_y(window, 2)) // 2

    # 実行
    _drag_grip(window, 0, between)

    # 検証
    assert _edge_texts(window) == ["B", "A", "C"]


def test_edge_phrase_grip_action_when_dropped_on_own_row(open_window: Callable[..., Opened]) -> None:
    """自分の行の上で離すと、動かさない。変えた件数も増やさない。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"), ("C", "end"))
    window = opened.window

    # 実行
    _drag_grip(window, 1, _row_center_y(window, 1))

    # 検証
    assert _edge_texts(window) == ["A", "B", "C"]
    _click(window, "cancel_button")
    opened.closed.assert_called_once()


# === edge_phrase_text_{n} ===


def test_edge_phrase_text_action_when_alt_up(open_window: Callable[..., Opened]) -> None:
    """文言の欄で Alt+↑ を押すと行が 1 つ上へ動き、フォーカスは動かした行の文言の欄に残る。"""
    # 準備
    opened = _open_edge(open_window, ("A", "start"), ("B", "end"), ("C", "both"))
    window = opened.window

    # 実行
    _alt_key(window, 1, Qt.Key.Key_Up)

    # 検証
    assert _edge_texts(window) == ["B", "A", "C"]
    assert _edge_positions(window) == ["文末", "文頭", "両方"]
    assert window.focusWidget() is find(window, QLineEdit, "edge_phrase_text_0")


def test_edge_phrase_text_action_when_alt_down(open_window: Callable[..., Opened]) -> None:
    """文言の欄で Alt+↓ を押すと行が 1 つ下へ動き、フォーカスは動かした行の文言の欄に残る。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"), ("C", "end"))
    window = opened.window

    # 実行
    _alt_key(window, 0, Qt.Key.Key_Down)

    # 検証
    assert _edge_texts(window) == ["B", "A", "C"]
    assert window.focusWidget() is find(window, QLineEdit, "edge_phrase_text_1")


def test_edge_phrase_text_action_when_alt_at_edge(open_window: Callable[..., Opened]) -> None:
    """先頭で Alt+↑、末尾で Alt+↓ を押しても何も動かない。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"))
    window = opened.window

    # 実行
    _alt_key(window, 0, Qt.Key.Key_Up)
    _alt_key(window, 1, Qt.Key.Key_Down)

    # 検証
    assert _edge_texts(window) == ["A", "B"]
    assert window.focusWidget() is find(window, QLineEdit, "edge_phrase_text_1")


def test_edge_phrase_text_action_when_typed(open_window: Callable[..., Opened]) -> None:
    """Alt を押さない矢印は欄の入力として働き、行は動かない。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"))
    window = opened.window
    edit = find(window, QLineEdit, "edge_phrase_text_1")
    edit.setFocus()

    # 実行
    QTest.keyClick(edit, Qt.Key.Key_Up)

    # 検証
    assert _edge_texts(window) == ["A", "B"]


# === edge_phrase_position_{n} ===


def test_edge_phrase_position_options(open_window: Callable[..., Opened]) -> None:
    """位置の選択の選択肢は、文頭・文末・両方の順に並ぶ。"""
    # 実行
    opened = _open_edge(open_window, ("A", "end"))

    # 検証
    box = find(opened.window, QComboBox, "edge_phrase_position_0")
    assert [box.itemText(index) for index in range(box.count())] == ["文頭", "文末", "両方"]


def test_edge_phrase_position_action(open_window: Callable[..., Opened]) -> None:
    """位置を選び直すと、保存で edge_phrases の position に start・end・both として書く。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"), ("C", "end"))
    find(opened.window, QComboBox, "edge_phrase_position_0").setCurrentText("文頭")
    find(opened.window, QComboBox, "edge_phrase_position_2").setCurrentText("両方")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    saved = opened.deps.save_settings.call_args.args[0]
    assert [phrase.position for phrase in saved.edge_phrases] == ["start", "end", "both"]


# === edge_phrase_remove_{n} ===


def test_edge_phrase_remove_action(open_window: Callable[..., Opened]) -> None:
    """消すと一覧から外す。保存するまで settings.toml には書かない。"""
    # 準備
    opened = _open_edge(open_window, ("A", "start"), ("B", "end"), ("C", "both"))
    window = opened.window

    # 実行
    _click(window, "edge_phrase_remove_1")

    # 検証
    assert _edge_texts(window) == ["A", "C"]
    assert _edge_positions(window) == ["文頭", "両方"]
    opened.deps.save_settings.assert_not_called()
    assert find(window, QPushButton, "edge_phrase_remove_0").accessibleName() == "1 行目を消す"


def test_edge_phrase_remove_when_cancelled(open_window: Callable[..., Opened]) -> None:
    """消してからキャンセルして捨てると、settings.toml には書かず、開き直すと消す前の行が出る。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"))
    _click(opened.window, "edge_phrase_remove_0")
    driver = ModalDriver()
    driver.answer("discard_button")

    # 実行
    _click(opened.window, "cancel_button")

    # 検証
    driver.verify()
    opened.deps.save_settings.assert_not_called()
    opened.closed.assert_called_once()
    reopened = open_window(opened.deps.get_settings())
    find(reopened.window, QListWidget, "group_menu").setCurrentRow(EDGE_GROUP_ROW)
    assert _edge_texts(reopened.window) == ["A", "B"]


def test_edge_phrase_remove_when_last(open_window: Callable[..., Opened]) -> None:
    """最後の 1 行を消すと空の文が出て、保存すると edge_phrases は空になる。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"))

    # 実行
    _click(opened.window, "edge_phrase_remove_0")
    assert find(opened.window, QLabel, "edge_phrase_empty").isVisible()
    _click(opened.window, "save_button")

    # 検証
    assert opened.deps.save_settings.call_args.args[0].edge_phrases == []


# === add_edge_phrase_button ===


def test_add_edge_phrase_button_action(open_window: Callable[..., Opened]) -> None:
    """文言が空で位置が文末の行を末尾に足し、その行の文言の欄へフォーカスを移す。"""
    # 準備
    opened = _open_edge(open_window, ("A", "start"))
    window = opened.window

    # 実行
    _click(window, "add_edge_phrase_button")

    # 検証
    assert _edge_texts(window) == ["A", ""]
    assert _edge_positions(window) == ["文頭", "文末"]
    assert window.focusWidget() is find(window, QLineEdit, "edge_phrase_text_1")


def test_add_edge_phrase_button_when_no_phrases(open_window: Callable[..., Opened]) -> None:
    """行が 1 つも無いときに足すと、空の文を隠して 1 行目が出る。"""
    # 準備
    opened = _open_edge(open_window)

    # 実行
    _click(opened.window, "add_edge_phrase_button")

    # 検証
    assert not find(opened.window, QLabel, "edge_phrase_empty").isVisible()
    assert _edge_texts(opened.window) == [""]


# === save_button（ハルシネーション） ===


def test_save_button_when_edge_phrases_changed(open_window: Callable[..., Opened]) -> None:
    """一覧の順に edge_phrases を書く。文言が空の行は捨て、前後の空白は除く。再起動せずに効く値として書き、窓を開いたまま保存した知らせを出す。"""
    # 準備（「お疲れ様でした」（文頭）を足して先頭へ動かし、空の行を足したままにして、「ありがとうございました」の行を消す）
    opened = _open_edge(
        open_window, ("チャンネル登録*", "end"), ("ご視聴ありがとうございました", "end"), ("ありがとうございました", "end")
    )
    window = opened.window
    _click(window, "add_edge_phrase_button")
    find(window, QLineEdit, "edge_phrase_text_3").setText("  お疲れ様でした  ")
    find(window, QComboBox, "edge_phrase_position_3").setCurrentText("文頭")
    _click(window, "add_edge_phrase_button")
    _alt_key(window, 3, Qt.Key.Key_Up)
    _alt_key(window, 2, Qt.Key.Key_Up)
    _alt_key(window, 1, Qt.Key.Key_Up)
    _click(window, "edge_phrase_remove_3")

    # 実行
    _click(window, "save_button")

    # 検証
    saved = opened.deps.save_settings.call_args.args[0]
    assert [(phrase.text, phrase.position) for phrase in saved.edge_phrases] == [
        ("お疲れ様でした", "start"),
        ("チャンネル登録*", "end"),
        ("ご視聴ありがとうございました", "end"),
    ]
    opened.saved.assert_called_once()
    opened.closed.assert_not_called()
    assert find(window, QLabel, "saved_notice").text() == "保存しました。"
    assert not find(window, QLabel, "restart_notice").isVisible()


def test_reset_dialog_when_edge_phrases(open_window: Callable[..., Opened]) -> None:
    """「既定に戻す」は、文頭・文末から消す文言を既定の 3 行（全て文末）に戻す。"""
    # 準備
    opened = _open_edge(open_window, ("えーと", "start"))
    driver = ModalDriver()
    driver.answer("reset_button")

    # 実行
    _click(opened.window, "reset_button")

    # 検証
    driver.verify()
    assert _edge_texts(opened.window) == ["チャンネル登録*", "ご視聴ありがとうございました", "ありがとうございました"]
    assert _edge_positions(opened.window) == ["文末", "文末", "文末"]


# === input_checks（ハルシネーション） ===

WILDCARD_ONLY_MESSAGE = "* だけの文言は、文頭・文末の行を丸ごと消します。消したい文言を入れてください。"
"""文言が `*` だけのときの文言。"""


def test_input_check_when_edge_phrase_wildcard_only(open_window: Callable[..., Opened]) -> None:
    """`*` だけの文言: 保存を止め、欄の下とエラーの一覧（「ハルシネーションの {n} 行目の文言」）に文言を出す。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"))
    find(opened.window, QLineEdit, "edge_phrase_text_1").setText("*")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_not_called()
    assert f"ハルシネーションの 2 行目の文言: {WILDCARD_ONLY_MESSAGE}" in _error_rows(opened.window)
    assert WILDCARD_ONLY_MESSAGE in _field_errors(opened.window)
    assert find(opened.window, QLineEdit, "edge_phrase_text_1").text() == "*"


def test_input_check_when_edge_phrase_wildcard_only_with_spaces(open_window: Callable[..., Opened]) -> None:
    """前後に空白のある `*` だけの文言も止める。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"))
    find(opened.window, QLineEdit, "edge_phrase_text_0").setText("  *  ")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    opened.deps.save_settings.assert_not_called()
    assert f"ハルシネーションの 1 行目の文言: {WILDCARD_ONLY_MESSAGE}" in _error_rows(opened.window)


def test_input_check_when_edge_phrase_wildcard_with_text(open_window: Callable[..., Opened]) -> None:
    """`*` を含む文言は止めない（文言を持つ `*` は書ける）。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"))
    find(opened.window, QLineEdit, "edge_phrase_text_0").setText("字幕*")

    # 実行
    _click(opened.window, "save_button")

    # 検証
    assert opened.deps.save_settings.call_args.args[0].edge_phrases[0].text == "字幕*"


def test_input_check_when_edge_phrase_fixed(open_window: Callable[..., Opened]) -> None:
    """直して保存し直すと、書く。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"))
    find(opened.window, QLineEdit, "edge_phrase_text_0").setText("*")
    _click(opened.window, "save_button")
    opened.deps.save_settings.assert_not_called()

    # 実行
    find(opened.window, QLineEdit, "edge_phrase_text_0").setText("字幕")
    _click(opened.window, "save_button")

    # 検証
    assert opened.deps.save_settings.call_args.args[0].edge_phrases[0].text == "字幕"


def test_error_summary_row_action_when_edge_phrase(open_window: Callable[..., Opened]) -> None:
    """エラーの一覧の行を押すと、ハルシネーションのまとまりへ切り替えて、その行の文言の欄へフォーカスを移す。"""
    # 準備
    opened = _open_edge(open_window, ("A", "end"), ("B", "end"))
    find(opened.window, QLineEdit, "edge_phrase_text_1").setText("*")
    _click(opened.window, "save_button")
    find(opened.window, QListWidget, "group_menu").setCurrentRow(0)
    link = next(
        label for label in find(opened.window, QFrame, "error_summary").findChildren(QLabel)
        if "href" in label.text()
    )

    # 実行
    link.linkActivated.emit("edge_phrases[1].text")

    # 検証
    assert find(opened.window, QListWidget, "group_menu").currentRow() == EDGE_GROUP_ROW
    assert opened.window.focusWidget() is find(opened.window, QLineEdit, "edge_phrase_text_1")


# === discard_body（出力先のプリセットの変更の件数） ===

KIND_GROUP_ROWS = {"browser": 1, "endpoint": 2}
"""まとまりのメニューの種類のタブの行（ブラウザ添付・エンドポイントへ送る）。"""


def _three_browser_presets() -> Settings:
    """ブラウザ添付 3 件のプリセットを持つ設定を作る。"""
    from voice_paste.shared.settings import BrowserPreset

    return SETTINGS_MODEL(
        presets=[
            BrowserPreset(title="A", url="https://a.example"),
            BrowserPreset(title="B", url="https://b.example"),
            BrowserPreset(title="C", url="https://c.example"),
        ]
    )


def _select_kind(window: QWidget, kind: str) -> None:
    """まとまりのメニューで、種類のタブを選ぶ。"""
    find(window, QListWidget, "group_menu").setCurrentRow(KIND_GROUP_ROWS[kind])


def _preset_button(window: QWidget, kind: str, prefix: str, number: int) -> QPushButton:
    """種類のタブの number 件目のプリセットの操作のボタン（`{prefix}_{n}`）を引く。"""
    found = _panel(window, kind).findChild(QPushButton, f"{prefix}_{number}")
    assert found is not None, f"{kind} の {number} 件目の {prefix} のボタンが無い"
    return found


def _press_preset_hotkey(window: QWidget, kind: str, number: int) -> None:
    """種類のタブの number 件目のプリセットの確定のホットキーに、Ctrl+Alt+9 を押す。"""
    edit = _preset_field(window, kind, number, "hotkey", QLineEdit)
    edit.setFocus()
    QTest.keyClick(
        edit,
        Qt.Key.Key_9,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )


def test_discard_body_when_preset_added(open_window: Callable[..., Opened]) -> None:
    """プリセットを 1 つ足すと、変えた件数は 1 件（タイトルと URL を入れても 1 件）。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _add_preset(opened.window, "browser", "足した", "https://added.example")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_preset_removed(open_window: Callable[..., Opened]) -> None:
    """プリセットを 1 つ消すと、変えた件数は 1 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _preset_button(opened.window, "browser", "preset_remove", 0).click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_preset_changed_twice(open_window: Callable[..., Opened]) -> None:
    """1 つのプリセットの項目を 2 つ（タイトルと URL）変えても、変えた件数は 1 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _preset_field(opened.window, "browser", 0, "title", QLineEdit).setText("変えた")
    _preset_field(opened.window, "browser", 0, "url", QLineEdit).setText("https://changed.example")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_preset_hotkey_and_send_enter_changed(
    open_window: Callable[..., Opened],
) -> None:
    """ブラウザ添付の 1 つのプリセットのホットキーと Enter まで送るを変えても、変えた件数は 1 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _press_preset_hotkey(opened.window, "browser", 0)
    _preset_field(opened.window, "browser", 0, "send_enter", QCheckBox).click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_preset_hotkey_and_authorization_changed(
    open_window: Callable[..., Opened],
) -> None:
    """エンドポイントへ送るの 1 つのプリセットのホットキーと Authorization を変えても、変えた件数は 1 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "endpoint")
    _press_preset_hotkey(opened.window, "endpoint", 0)
    _preset_field(opened.window, "endpoint", 0, "authorization", QLineEdit).setText("Bearer y")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_preset_moved(open_window: Callable[..., Opened]) -> None:
    """プリセットを並べ替える（2 件のうち下を上へ）と、変えた件数は並べ替えの 1 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _preset_button(opened.window, "browser", "preset_up", 1).click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_two_presets_changed(open_window: Callable[..., Opened]) -> None:
    """2 つのプリセットの項目を 1 つずつ変えると、変えた件数は 2 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _preset_field(opened.window, "browser", 0, "title", QLineEdit).setText("変えた1")
    _preset_field(opened.window, "browser", 1, "url", QLineEdit).setText("https://changed.example")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(2)


def test_discard_body_when_preset_removed_from_middle(open_window: Callable[..., Opened]) -> None:
    """3 件のうち途中のプリセットを消すと、変えた件数は消した 1 件（残ったプリセットの順は並べ替えに数えない）。"""
    # 準備
    opened = open_window(_three_browser_presets())
    _select_kind(opened.window, "browser")
    _preset_button(opened.window, "browser", "preset_remove", 1).click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


def test_discard_body_when_presets_changed_in_two_kinds(open_window: Callable[..., Opened]) -> None:
    """ブラウザ添付とエンドポイントへ送るのタブで 1 つずつプリセットを変えると、変えた件数は 2 件。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _preset_field(opened.window, "browser", 0, "title", QLineEdit).setText("変えた1")
    _select_kind(opened.window, "endpoint")
    _preset_field(opened.window, "endpoint", 0, "title", QLineEdit).setText("変えた2")

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(2)


def test_discard_body_when_preset_moved_after_saved(open_window: Callable[..., Opened]) -> None:
    """保存してから並べ替えると、変えた件数は並べ替えの 1 件（保存で変えた分は数えない）。"""
    # 準備
    opened = open_window(_settings_with_presets())
    _select_kind(opened.window, "browser")
    _preset_field(opened.window, "browser", 0, "title", QLineEdit).setText("変えた")
    _click(opened.window, "save_button")
    _preset_button(opened.window, "browser", "preset_down", 0).click()

    # 実行
    body = _discard_body(opened)

    # 検証
    assert body == _discard_message(1)


# === 設定画面を開いている間はホットキーを止める ===


@pytest.mark.parametrize("route", ["save_and_restart", "cancel", "window_close"])
def test_settings_window_suspends_hotkeys(make_ui: Callable[..., Ui], route: str) -> None:
    """開いている間はホットキーの受付を止め（欄で押したキーで録音や確定が動かない）、どの経路で閉じても今の設定で張り直す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.open_settings()
    window = ui.controller._settings_window
    suspended_while_open = ui.deps.suspend_hotkeys.call_count
    resumed_while_open = ui.deps.resume_hotkeys.call_count
    if route == "save_and_restart":
        _set_text(window, RESTART_KEY, "12")
        _click(window, "save_and_restart_button")
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


def test_settings_window_when_saved(make_ui: Callable[..., Ui]) -> None:
    """「保存」では設定画面が開いたままなので、ホットキーの受付は止めたまま。閉じたときに今の設定で張り直す。"""
    # 準備
    ui = make_ui()
    ui.controller.open_settings()
    window = ui.controller._settings_window

    # 実行
    _click(window, "save_button")
    resumed_after_save = ui.deps.resume_hotkeys.call_count
    _click(window, "cancel_button")

    # 検証
    assert resumed_after_save == 0
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


# === 印の見え方（チェックボックス・ラジオボタン・選択欄の開く印） ===

THEME_PARAMS = [pytest.param("light", id="light"), pytest.param("dark", id="dark")]
"""印の見え方を確かめる明暗の組。"""

ARROW_AREA_WIDTH = 28
"""選択欄の右端の、開く印の区画の幅（論理ピクセル）。"""

ARROW_AREA_INSET = 6
"""開く印の区画を調べるとき、欄の外側の枠の線を避ける上下の余白（論理ピクセル）。"""

MIN_INDICATOR_CONTRAST = 3
"""印と背景の明るさの比の下限（WCAG 2.1 の 1.4.11）。"""


@pytest.fixture
def themed_window(
    open_window: Callable[..., Opened], apply_theme_to_app: Callable[[str], None]
) -> Callable[[str], SettingsWindow]:
    """明暗を当ててから設定画面（既定の設定）を開く関数を返す。"""

    def _open(theme: str) -> SettingsWindow:
        """明暗を当てて設定画面を開く。"""
        apply_theme_to_app(theme)
        return open_window().window

    return _open


def _show_field(window: QWidget, key: str, cls: type = QWidget) -> Any:
    """設定のキーの欄が出ているまとまりへ切り替えて、その欄を返す。"""
    from PySide6.QtWidgets import QApplication

    menu = find(window, QListWidget, "group_menu")
    for row in range(menu.count()):
        menu.setCurrentRow(row)
        QApplication.processEvents()
        field = _field(window, key, cls)
        if field.isVisible():
            return field
    raise AssertionError(f"{key} の欄が出ているまとまりが無い")


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_checkbox_on(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """オンのチェックボックスは、箱を accent_fg で塗り、チェックを surface で描く（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備: 録音のまとまりの、オンのチェックボックス
    window = themed_window(theme)
    checkbox = _show_field(window, "recording.lower_volume", QCheckBox)

    # 実行
    image = indicator_image(checkbox)

    # 検証
    colors = load_tokens()["color"][theme]
    assert checkbox.isChecked()
    assert count_near(image, colors["accent_fg"]) > 0
    assert count_closer(image, colors["surface"], colors["accent_fg"]) > 0


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_checkbox_off(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """オフのチェックボックスは、箱を text_muted の線で囲み、accent_fg の画素が無い（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備: 録音のまとまりの、オフのチェックボックス
    window = themed_window(theme)
    checkbox = _show_field(window, "recording.hide_window", QCheckBox)

    # 実行
    image = indicator_image(checkbox)

    # 検証
    colors = load_tokens()["color"][theme]
    assert not checkbox.isChecked()
    assert count_near(image, colors["text_muted"]) > 0
    assert count_near(image, colors["accent_fg"]) == 0


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_checkbox_disabled(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """使えないオンのチェックボックスは、箱を border で塗りチェックを text_muted で描き、名前を text_muted にする（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備: オンのチェックボックスを使えなくする
    window = themed_window(theme)
    checkbox = _show_field(window, "recording.lower_volume", QCheckBox)
    checkbox.setEnabled(False)

    # 実行
    image = indicator_image(checkbox)
    name_image = checkbox.grab().toImage()

    # 検証
    colors = load_tokens()["color"][theme]
    assert count_near(image, colors["border"]) > 0
    assert count_closer(image, colors["text_muted"], colors["border"]) > 0
    assert count_near(image, colors["accent_fg"]) == 0
    assert count_near(name_image, colors["text_muted"]) > count_near(image, colors["text_muted"])


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_radio_checked(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """選んだラジオボタンの丸の中心は accent_fg の点で、選んでいないラジオボタンの中心は accent_fg でない（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備: 画面の明暗の欄のラジオボタン（既定の「Windows の設定に従う」が選ばれている）
    window = themed_window(theme)
    buttons = _show_field(window, "ui.theme").findChildren(QRadioButton)
    checked = next(button for button in buttons if button.isChecked())
    unchecked = next(button for button in buttons if not button.isChecked())

    # 実行
    checked_image = indicator_image(checked)
    unchecked_image = indicator_image(unchecked)

    # 検証
    accent_fg = load_tokens()["color"][theme]["accent_fg"]
    center = (checked_image.width() // 2, checked_image.height() // 2)
    assert color_distance(checked_image.pixelColor(*center), accent_fg) <= COLOR_TOLERANCE
    assert count_near(unchecked_image, accent_fg) == 0


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_radio_disabled(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """使えない選んだラジオボタンは、丸の中を塗らず、点を text_muted で描く（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備: 選んだラジオボタンを使えなくする
    window = themed_window(theme)
    buttons = _show_field(window, "ui.theme").findChildren(QRadioButton)
    checked = next(button for button in buttons if button.isChecked())
    checked.setEnabled(False)

    # 実行
    image = indicator_image(checked)

    # 検証
    colors = load_tokens()["color"][theme]
    center = (image.width() // 2, image.height() // 2)
    assert color_distance(image.pixelColor(*center), colors["text_muted"]) <= COLOR_TOLERANCE
    assert count_near(image, colors["accent_fg"]) == 0
    assert count_near(image, colors["sunken"]) == 0


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_focused(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """フォーカスを受けると、印と名前の組を accent_fg の枠で囲む。枠は印と名前の幅に収まる（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備: オフのチェックボックス（印の中に accent_fg が出ない）
    window = themed_window(theme)
    checkbox = _show_field(window, "recording.hide_window", QCheckBox)
    accent_fg = load_tokens()["color"][theme]["accent_fg"]
    before = count_near(checkbox.grab().toImage(), accent_fg)

    # 実行
    checkbox.setFocus(Qt.FocusReason.TabFocusReason)
    after = count_near(checkbox.grab().toImage(), accent_fg)

    # 検証
    assert checkbox.hasFocus()
    assert before == 0
    assert after > 0
    assert checkbox.width() <= checkbox.sizeHint().width()


def test_check_indicator_when_indicator_gap(
    themed_window: Callable[[str], SettingsWindow],
) -> None:
    """印と名前の間は 8px、ラジオボタンの選択肢の間は 20px（正常系）。"""
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    # 準備
    window = themed_window("light")
    checkbox = _show_field(window, "recording.lower_volume", QCheckBox)
    radios = _show_field(window, "ui.theme").findChildren(QRadioButton)
    option = QStyleOptionButton()
    option.initFrom(checkbox)

    # 実行
    indicator = checkbox.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox
    )
    contents = checkbox.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxContents, option, checkbox
    )

    # 検証
    assert contents.left() - indicator.right() - 1 == 8
    assert radios[1].x() - (radios[0].x() + radios[0].width()) == 20


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_combo_arrow(
    themed_window: Callable[[str], SettingsWindow], theme: str
) -> None:
    """選択欄は、右端に別の枠を持たせず、text_muted の線の V 字を置く（正常系）。"""
    from PySide6.QtCore import QRect

    from voice_paste.ui.style import load_tokens

    # 準備: 文字起こしのエンジンの選択欄
    window = themed_window(theme)
    combo = _show_field(window, "transcription.engine", QComboBox)
    image = combo.grab().toImage()
    area = QRect(combo.width() - ARROW_AREA_WIDTH, 0, ARROW_AREA_WIDTH, combo.height())
    # 区画の左の縁（区切りの縦線が出る場所）は、欄の外側の枠の線を避けて上下を縮める
    divider = QRect(area.x(), ARROW_AREA_INSET, 4, combo.height() - 2 * ARROW_AREA_INSET)

    # 実行
    arrow_count = count_near(crop_logical(image, area), load_tokens()["color"][theme]["text_muted"])
    divider_count = count_near(crop_logical(image, divider), load_tokens()["color"][theme]["border"])

    # 検証
    assert arrow_count > 0
    assert divider_count == 0


@pytest.mark.parametrize("theme", THEME_PARAMS)
def test_check_indicator_when_contrast(theme: str) -> None:
    """印の色と背景の明るさの比が 3:1 以上（正常系）。"""
    from voice_paste.ui.style import load_tokens

    # 準備
    colors = load_tokens()["color"][theme]

    # 実行
    ratios = [
        contrast_ratio(colors[mark], colors[background])
        for mark in ("text_muted", "accent_fg")
        for background in ("bg", "surface", "sunken")
    ]
    check_ratio = contrast_ratio(colors["surface"], colors["accent_fg"])

    # 検証
    assert min(ratios) >= MIN_INDICATOR_CONTRAST
    assert check_ratio >= MIN_INDICATOR_CONTRAST
