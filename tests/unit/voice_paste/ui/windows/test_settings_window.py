"""ui/windows/settings_window.py（SettingsWindow の save・close_without_confirm、format_hotkey・parse_hotkey・to_field_message）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。UiDeps の関数は Mock に差し替える。
欄は画面設計の項目 ID（field_{キー}・error_summary）の objectName で引く。キーは設定のキーで、エラーの一覧と同じ書式（`outputs[0].enter_delay_sec`）。
エラーの一覧（error_summary）は、行ごとの QLabel（欄へのリンクを含んでよい）で組まれる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QKeyCombination, QRegularExpression, Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QAccessibleEvent, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QRadioButton,
    QSlider,
    QWidget,
)

from tests.unit.voice_paste.ui.helpers import make_ui_deps

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings, Settings
    from voice_paste.shared.types import GlossaryEntry
    from voice_paste.ui.controller import UiDeps
    from voice_paste.ui.windows.settings_window import SettingsWindow

ENTER_DELAY_DESCRIPTION = "貼り付けてから Enter を送信するまで待つ秒数"
NEW_VOLUME_PERCENT = 30
VOLUME_KEYS = (
    "recording.lower_volume",
    "recording.volume_percent",
    "recording.fade_sec",
)
"""Linux の設定画面に出さない、録音中の音量の設定のキー。"""


@dataclass
class Opened:
    """開いた設定画面と、渡した UiDeps。"""

    window: SettingsWindow
    deps: UiDeps


@pytest.fixture
def opened(qapp: QApplication, tmp_path: Path) -> Iterator[Opened]:
    """既定の設定で設定画面を開き、テストの後に隠す。"""
    from voice_paste.ui.windows.settings_window import SettingsWindow

    deps = make_ui_deps(tmp_path)
    window = SettingsWindow(deps)
    window.show()
    yield Opened(window=window, deps=deps)
    window.hide()


def _field(window: SettingsWindow, key: str) -> QWidget:
    """設定のキーの欄（objectName が field_{キー}）を返す。"""
    widget = window.findChild(QWidget, f"field_{key}")
    assert widget is not None, f"field_{key} の欄が無い"
    return widget


def _existing_fields(window: SettingsWindow, keys: tuple[str, ...]) -> list[str]:
    """設定のキーのうち、欄（objectName が field_{キー}）が置かれているものを並べて返す。"""
    return [key for key in keys if window.findChild(QWidget, f"field_{key}") is not None]


def _enter_modifier_checkbox(window: SettingsWindow, value: str) -> QAbstractButton:
    """貼り付けて送信の「Enter と一緒に押す修飾キー」の、値のチェックボックス（objectName が field_{キー}_{値}）を返す。"""
    checkbox = _field(window, f"outputs[0].enter_modifiers_{value}")
    assert isinstance(checkbox, QAbstractButton)
    return checkbox


def _error_summary_text(window: SettingsWindow) -> str:
    """エラーの一覧の行（QLabel）の文字を、リンクの書式を外して改行で並べて返す。"""
    summary = window.findChild(QWidget, "error_summary")
    assert summary is not None
    labels = [summary, *summary.findChildren(QLabel)]
    lines: list[str] = []
    for label in labels:
        if isinstance(label, QLabel):
            document = QTextDocument()
            document.setHtml(label.text())
            lines.append(document.toPlainText())
    return "\n".join(lines)


def _add_preset(window: SettingsWindow, kind: str, *, title: str, url: str) -> None:
    """種類のタブの「プリセットを追加」を押し、追加したプリセットのタイトルと URL の欄に値を入れる。"""
    button = window.findChild(QAbstractButton, f"add_preset_button_{kind}")
    assert button is not None, f"add_preset_button_{kind} のボタンが無い"
    button.click()
    panel = window.findChild(QWidget, f"preset_list_{kind}")
    assert panel is not None, f"preset_list_{kind} の一覧が無い"
    for field, value in (("title", title), ("url", url)):
        edits = panel.findChildren(QLineEdit, QRegularExpression(f"^preset_{field}_"))
        assert len(edits) == 1, f"preset_{field}_ の欄が 1 つでない"
        edits[0].setText(value)


@pytest.fixture
def open_with_glossaries(
    qapp: QApplication, tmp_path: Path
) -> Iterator[Callable[..., Opened]]:
    """用語集の一覧と行を指定して設定画面を開く関数を返す。開いた窓はテストの後に隠す。"""
    from voice_paste.ui.windows.settings_window import SettingsWindow

    windows: list[SettingsWindow] = []

    def _open(
        glossaries: list[GlossarySettings],
        rows: Mapping[Path, list[GlossaryEntry]],
        *,
        settings: Settings | None = None,
        presets: list[GlossaryPresetSettings] | None = None,
    ) -> Opened:
        """list_glossaries が glossaries を返し、read_glossary が場所の行を返す UiDeps で開く。presets を渡すと、list_glossary_presets がそれを返す。"""
        overrides = {} if presets is None else {"list_glossary_presets": MagicMock(return_value=presets)}
        deps = make_ui_deps(
            tmp_path,
            settings=settings,
            list_glossaries=MagicMock(return_value=glossaries),
            read_glossary=MagicMock(side_effect=lambda path: list(rows[path])),
            **overrides,
        )
        window = SettingsWindow(deps)
        window.show()
        windows.append(window)
        return Opened(window=window, deps=deps)

    yield _open

    for window in windows:
        window.hide()


def _select_group(window: SettingsWindow, name: str) -> None:
    """左のメニュー（group_menu）で、名前のまとまりを選ぶ。"""
    menu = window.findChild(QListWidget, "group_menu")
    assert menu is not None
    items = menu.findItems(name, Qt.MatchFlag.MatchExactly)
    assert len(items) == 1, f"{name} のまとまりが無い"
    menu.setCurrentItem(items[0])


def _button(window: SettingsWindow, name: str) -> QAbstractButton:
    """objectName が name のボタンを返す。"""
    button = window.findChild(QAbstractButton, name)
    assert button is not None, f"{name} のボタンが無い"
    return button


def _visible_edits(window: SettingsWindow, prefix: str) -> list[QLineEdit]:
    """画面に出ている、objectName が prefix で始まる文字の欄を、名前の順で返す。"""
    found = window.findChildren(QLineEdit, QRegularExpression(f"^{prefix}"))
    return sorted(
        (edit for edit in found if edit.isVisible()), key=lambda edit: edit.objectName()
    )


def _visible_buttons(window: SettingsWindow, prefix: str) -> list[QAbstractButton]:
    """画面に出ている、objectName が prefix で始まるボタンを、名前の順で返す。"""
    found = window.findChildren(QAbstractButton, QRegularExpression(f"^{prefix}"))
    return sorted(
        (button for button in found if button.isVisible()), key=lambda button: button.objectName()
    )


def _add_preset_glossary(window: SettingsWindow, name: str) -> None:
    """追加する用語集の選択で name を選び、使う用語集の追加ボタンを押す。"""
    combo = window.findChild(QComboBox, "glossary_preset_glossary_select")
    assert combo is not None, "glossary_preset_glossary_select の選択の欄が無い"
    combo.setCurrentIndex(combo.findText(name))
    _button(window, "glossary_preset_glossary_add").click()


def _label(window: SettingsWindow, name: str) -> QLabel:
    """objectName が name の文字の表示を返す。"""
    label = window.findChild(QLabel, name)
    assert label is not None, f"{name} の表示が無い"
    return label


def _press_hotkey(window: SettingsWindow, name: str) -> None:
    """objectName が name のホットキーの欄に、Ctrl+Alt+9 を押して入れる。"""
    edit = window.findChild(QLineEdit, name)
    assert edit is not None, f"{name} の欄が無い"
    QTest.keyClick(
        edit,
        Qt.Key.Key_9,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )


def _set_model(window: SettingsWindow, model: str) -> None:
    """「文字起こし」のモデルの欄（「再起動で反映」）に値を入れる。"""
    combo = _field(window, "transcription.local_whisper.model")
    assert isinstance(combo, QComboBox)
    combo.setCurrentText(model)


def _set_language(window: SettingsWindow, language: str) -> None:
    """「文字起こし」の言語の欄（「再起動で反映」）に値を入れる。"""
    edit = _field(window, "transcription.local_whisper.language")
    assert isinstance(edit, QLineEdit)
    edit.setText(language)


# === save ===


def test_save(opened: Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    """通った値を書き、設定画面を開いたまま保存したメッセージを出して読み上げにも伝える（正常系）。"""
    # 準備（読み上げに渡すイベントを控える）
    announced: list[QAccessibleEvent] = []
    monkeypatch.setattr(QAccessible, "updateAccessibility", announced.append)
    saved_count: list[int] = []
    closed_count: list[int] = []
    opened.window.saved.connect(lambda: saved_count.append(1))
    opened.window.closed.connect(lambda: closed_count.append(1))
    _select_group(opened.window, "録音")
    volume = _field(opened.window, "recording.volume_percent")
    assert isinstance(volume, QSlider)
    volume.setValue(NEW_VOLUME_PERCENT)

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].recording.volume_percent == NEW_VOLUME_PERCENT
    assert saved_count == [1]
    assert closed_count == []
    assert opened.window.isVisible()
    notice = _label(opened.window, "saved_notice")
    assert notice.isVisible()
    assert notice.text() == "保存しました。"
    assert volume.value() == NEW_VOLUME_PERCENT
    menu = opened.window.findChild(QListWidget, "group_menu")
    assert menu is not None
    assert menu.currentItem().text() == "録音"
    assert len(announced) == 1
    assert isinstance(announced[0], QAccessibleAnnouncementEvent)
    assert announced[0].message() == "保存しました。"


def test_save_when_invalid(opened: Opened) -> None:
    """通らなければ書かずにエラーを出す（異常系）。"""
    # 準備
    enter_delay = _field(opened.window, "outputs[0].enter_delay_sec")
    assert isinstance(enter_delay, QLineEdit)
    enter_delay.setText("abc")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    assert f"{ENTER_DELAY_DESCRIPTION}: 数値を入れてください（例: 0.5）。" in _error_summary_text(
        opened.window
    )
    assert enter_delay.text() == "abc"


def test_save_when_fixed_after_invalid(opened: Opened) -> None:
    """修正して保存し直すと、前に出したエラーを削除する（正常系）。"""
    # 準備（abc を入れて保存し、エラーの一覧と欄の下のエラーを出してから 0.5 に修正する）
    enter_delay = _field(opened.window, "outputs[0].enter_delay_sec")
    assert isinstance(enter_delay, QLineEdit)
    enter_delay.setText("abc")
    assert opened.window.save(restart=False) is False
    enter_delay.setText("0.5")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    summary = opened.window.findChild(QWidget, "error_summary")
    assert summary is not None
    assert summary.isHidden()
    summary_layout = summary.layout()
    assert summary_layout is not None
    assert summary_layout.count() == 0
    field_error = _label(opened.window, "error_outputs[0].enter_delay_sec")
    assert field_error.isHidden()
    assert field_error.text() == ""
    notice = _label(opened.window, "saved_notice")
    assert notice.isVisible()
    assert notice.text() == "保存しました。"


def test_save_when_hotkey_unavailable(opened: Opened) -> None:
    """ホットキーを受け付けられなければエラーを出し、保存したメッセージを出さない（異常系）。"""
    from voice_paste.shared.errors import HotkeyError

    # 準備
    saved_count: list[int] = []
    opened.window.saved.connect(lambda: saved_count.append(1))
    opened.deps.save_settings.side_effect = HotkeyError("<ctrl>+<nokey> を読めない")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    assert "ホットキーを受け付けられませんでした" in _error_summary_text(opened.window)
    assert saved_count == []
    assert not _label(opened.window, "saved_notice").isVisible()
    assert opened.window.isVisible()


def test_save_when_presets(opened: Opened) -> None:
    """タブごとのプリセットを 1 つの一覧にして書く（正常系）。"""
    # 準備（エンドポイントへ送信のタブ → ブラウザ添付のタブの順に追加する）
    _add_preset(opened.window, "endpoint", title="受信先", url="http://127.0.0.1:9000/hook")
    _add_preset(opened.window, "browser", title="ChatGPT", url="https://chatgpt.com")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    saved_settings = opened.deps.save_settings.call_args.args[0]
    assert [(preset.kind, preset.title) for preset in saved_settings.presets] == [
        ("browser", "ChatGPT"),
        ("endpoint", "受信先"),
    ]


def test_save_when_preset_invalid(opened: Opened) -> None:
    """タイトルが空のプリセットは書かずにエラーを出す（異常系）。"""
    # 準備（URL だけ入れる）
    _add_preset(opened.window, "browser", title="", url="https://chatgpt.com")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    assert "プリセット 1 件目のタイトル: タイトルを入れてください。" in _error_summary_text(
        opened.window
    )


def test_save_when_enter_modifiers(opened: Opened) -> None:
    """オンにした修飾キーを一覧にして書く（正常系）。"""
    # 準備（Shift → Ctrl の順にオンにする）
    ctrl = _enter_modifier_checkbox(opened.window, "ctrl")
    alt = _enter_modifier_checkbox(opened.window, "alt")
    shift = _enter_modifier_checkbox(opened.window, "shift")
    shift.setChecked(True)
    ctrl.setChecked(True)

    # 実行
    result = opened.window.save(restart=False)

    # 検証（一覧は列挙の並び）
    assert result is True
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].outputs[0].enter_modifiers == [
        "ctrl",
        "shift",
    ]
    assert [ctrl.text(), alt.text(), shift.text()] == ["Ctrl", "Alt", "Shift"]


def test_save_when_theme(opened: Opened) -> None:
    """明暗の欄で選んだ値を保存する（正常系）。"""
    # 準備: ui.theme=system で開いた「画面の明暗」の「ライト」を選ぶ
    light = next(
        button
        for button in _field(opened.window, "ui.theme").findChildren(QRadioButton)
        if button.text() == "ライト"
    )
    light.setChecked(True)

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    opened.deps.save_settings.assert_called_once()
    assert opened.deps.save_settings.call_args.args[0].ui.theme == "light"


def test_save_when_glossaries(
    open_with_glossaries: Callable[..., Opened], settings_model: type[Settings], tmp_path: Path
) -> None:
    """用語集の一覧と補正に使うプリセットを設定に入れ、行を変えた用語集だけを書き戻しに渡す（正常系）。"""
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集と 2 件のプリセットを持つ設定で開き、2 件目の用語集の行を 1 つオフにして、補正に使うプリセットを 2 件目にする）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    second = GlossarySettings(name="会議用", path=tmp_path / "meeting.csv")
    presets = [
        GlossaryPresetSettings(name="既定", glossaries=["yogo"]),
        GlossaryPresetSettings(name="会議", glossaries=["会議用", "yogo"]),
    ]
    opened = open_with_glossaries(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [
                GlossaryEntry(wrong="い", right="B"),
                GlossaryEntry(wrong="う", right="C"),
            ],
        },
        settings=settings_model(glossaries=[first, second], glossary_presets=presets),
        presets=presets,
    )
    _select_group(opened.window, "用語集")
    _button(opened.window, "glossary_pick_1").click()
    _visible_buttons(opened.window, "glossary_entry_on_")[0].click()
    _button(opened.window, "glossary_preset_active_1").click()

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    opened.deps.save_settings.assert_called_once()
    saved_settings, changed_rows = opened.deps.save_settings.call_args.args
    assert [glossary.name for glossary in saved_settings.glossaries] == ["yogo", "会議用"]
    assert saved_settings.active_glossary_preset == "会議"
    assert saved_settings.glossary_path is None
    assert saved_settings.active_glossary is None
    assert changed_rows == {
        second.path: [
            GlossaryEntry(wrong="い", right="B", enabled=False),
            GlossaryEntry(wrong="う", right="C"),
        ]
    }


def test_save_when_glossaries_untouched(
    open_with_glossaries: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集を変えずに保存すると、書き戻す CSV は無い（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（今までの用語集 1 件だけの設定で開き、ホットキーだけを変える）
    glossary = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_with_glossaries(
        [glossary], {glossary.path: [GlossaryEntry(wrong="あ", right="A")]}
    )
    start_hotkey = opened.window.findChild(QLineEdit, "hotkey_hotkeys.start")
    assert start_hotkey is not None
    QTest.keyClick(
        start_hotkey,
        Qt.Key.Key_9,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    saved_settings, changed_rows = opened.deps.save_settings.call_args.args
    assert saved_settings.hotkeys.start == "<ctrl>+<alt>+9"
    assert saved_settings.glossaries == [glossary]
    assert changed_rows == {}


def test_save_when_glossary_invalid(
    open_with_glossaries: Callable[..., Opened], tmp_path: Path
) -> None:
    """名前の重なりと片方が空の行では保存せず、エラーを出す（異常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の用語集で開き、追加した用語集の名前を 2 件目と同じにして、その 2 行目の誤変換を空にする）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    second = GlossarySettings(name="会議用", path=tmp_path / "meeting.csv")
    opened = open_with_glossaries(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
    )
    _select_group(opened.window, "用語集")
    _button(opened.window, "add_glossary_button").click()
    _visible_edits(opened.window, "glossary_name_")[0].setText("会議用")
    add_entry = _button(opened.window, "add_glossary_entry_button")
    add_entry.click()
    add_entry.click()
    wrong_edits = _visible_edits(opened.window, "glossary_entry_wrong_")
    right_edits = _visible_edits(opened.window, "glossary_entry_right_")
    wrong_edits[0].setText("う")
    right_edits[0].setText("U")
    right_edits[1].setText("V")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    summary = _error_summary_text(opened.window)
    assert "用語集 3 件目の名前: 用語集「会議用」と同じ名前です" in summary
    assert "用語集 3 件目の 2 行目の誤変換: 誤変換を入れてください" in summary


def test_save_when_glossary_right_empty(
    open_with_glossaries: Callable[..., Opened], tmp_path: Path
) -> None:
    """正しい表記だけが空の行は確かめに通し、空のまま書き戻しに渡す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件目の用語集に行を追加して、誤変換「ご視聴ありがとうございました」だけを入れる）
    glossary = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_with_glossaries(
        [glossary], {glossary.path: [GlossaryEntry(wrong="あ", right="A")]}
    )
    _select_group(opened.window, "用語集")
    _button(opened.window, "add_glossary_entry_button").click()
    _visible_edits(opened.window, "glossary_entry_wrong_")[1].setText("ご視聴ありがとうございました")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    summary = opened.window.findChild(QWidget, "error_summary")
    assert summary is not None
    assert not summary.isVisible()
    opened.deps.save_settings.assert_called_once()
    _, changed_rows = opened.deps.save_settings.call_args.args
    assert changed_rows == {
        glossary.path: [
            GlossaryEntry(wrong="あ", right="A"),
            GlossaryEntry(wrong="ご視聴ありがとうございました", right=""),
        ]
    }


HINT_TOO_LONG_WORD_CHARS = 74
"""日本語 74 文字 = 222 バイトの語の文字数（これに英字 1 文字を追加すると 223 バイト）。"""


def _add_hint_preset(window: SettingsWindow, *, name: str, word_count: int) -> list[QLineEdit]:
    """「表記のヒント」でプリセットを追加して名前を入れ、語の欄を word_count 個追加して、語の欄を返す。"""
    _select_group(window, "表記のヒント")
    _button(window, "hint_preset_add").click()
    _visible_edits(window, "hint_preset_name_")[0].setText(name)
    for _ in range(word_count):
        _visible_buttons(window, "hint_word_add_")[0].click()
    return _visible_edits(window, r"hint_word_\d")


def test_save_when_glossary_presets(
    open_with_glossaries: Callable[..., Opened], settings_model: type[Settings], tmp_path: Path
) -> None:
    """用語集のプリセットを使う用語集の順のまま設定に入れる（正常系）。"""
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（glossary_presets が空で active_glossary = "会議用" の設定で開き、「既定」（["会議用"]）が出る。プリセットを追加して名前を「議事録」にし、「yogo」「会議用」の順に追加して、補正に使うプリセットに選ぶ）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    second = GlossarySettings(name="会議用", path=tmp_path / "meeting.csv")
    opened = open_with_glossaries(
        [first, second],
        {
            first.path: [GlossaryEntry(wrong="あ", right="A")],
            second.path: [GlossaryEntry(wrong="い", right="B")],
        },
        settings=settings_model(glossaries=[first, second], active_glossary="会議用"),
        presets=[GlossaryPresetSettings(name="既定", glossaries=["会議用"])],
    )
    _select_group(opened.window, "用語集")
    _button(opened.window, "add_glossary_preset_button").click()
    _visible_edits(opened.window, "glossary_preset_name_")[0].setText("議事録")
    _add_preset_glossary(opened.window, "yogo")
    _add_preset_glossary(opened.window, "会議用")
    _button(opened.window, "glossary_preset_active_1").click()

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    saved_settings, _changed_rows = opened.deps.save_settings.call_args.args
    assert saved_settings.glossary_presets == [
        GlossaryPresetSettings(name="既定", glossaries=["会議用"]),
        GlossaryPresetSettings(name="議事録", glossaries=["yogo", "会議用"]),
    ]
    assert saved_settings.active_glossary_preset == "議事録"
    assert saved_settings.active_glossary is None


def test_save_when_glossary_preset_invalid(
    open_with_glossaries: Callable[..., Opened], tmp_path: Path
) -> None:
    """用語集のプリセットの名前が空・重なるときは保存せず、エラーを出す（異常系）。"""
    from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（「既定」の 1 件のプリセットでプリセットを 2 つ追加し、2 件目の名前を「既定」に、3 件目の名前を空のままにする）
    glossary = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_with_glossaries(
        [glossary],
        {glossary.path: [GlossaryEntry(wrong="あ", right="A")]},
        presets=[GlossaryPresetSettings(name="既定", glossaries=["yogo"])],
    )
    _select_group(opened.window, "用語集")
    add_preset = _button(opened.window, "add_glossary_preset_button")
    add_preset.click()
    _visible_edits(opened.window, "glossary_preset_name_")[0].setText("既定")
    add_preset.click()

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    summary = _error_summary_text(opened.window)
    assert (
        "用語集のプリセット 2 件目の名前: 用語集のプリセット「既定」と同じ名前です。別の名前にしてください。"
        in summary
    )
    assert "用語集のプリセット 3 件目の名前: 名前を入れてください。" in summary
    duplicated_link = next(
        label
        for label in opened.window.findChild(QWidget, "error_summary").findChildren(QLabel)
        if "2 件目の名前" in label.text()
    )
    _select_group(opened.window, "出力先")
    duplicated_link.linkActivated.emit("glossary_presets[1].name")
    assert opened.window.focusWidget() is _visible_edits(opened.window, "glossary_preset_name_")[0]


def test_save_when_hint_presets(opened: Opened) -> None:
    """表記のヒントのプリセットを設定に入れて書く（正常系）。"""
    # 準備（「表記のヒント」でプリセットを 1 件追加して名前「開発」と語 voice-paste を入れる）
    word_edits = _add_hint_preset(opened.window, name="開発", word_count=1)
    word_edits[0].setText("voice-paste")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    saved_settings = opened.deps.save_settings.call_args.args[0]
    assert [
        (preset.name, preset.words, preset.enabled) for preset in saved_settings.hint_presets
    ] == [("開発", ["voice-paste"], True)]


def test_save_when_hint_too_long(opened: Opened) -> None:
    """有効なヒントが上限を超えたら書かずにエラーを出す（異常系）。"""
    # 準備（有効なプリセットにつないだ長さが 223 バイトになる語を入れる）
    word_edits = _add_hint_preset(opened.window, name="開発", word_count=1)
    word_edits[0].setText("a" + "あ" * HINT_TOO_LONG_WORD_CHARS)

    # 実行
    result = opened.window.save(restart=False)

    # 検証（エラーの一覧と、長さの行の下の両方に出る）
    message = "有効なヒントが長すぎます（223 / 222 バイト）。"
    assert result is False
    opened.deps.save_settings.assert_not_called()
    assert f"有効なヒントの長さ: {message}" in _error_summary_text(opened.window)
    summary = opened.window.findChild(QWidget, "error_summary")
    assert summary is not None
    below_length_row = [
        label
        for label in opened.window.findChildren(QLabel)
        if message in label.text() and not summary.isAncestorOf(label) and label is not summary
    ]
    assert len(below_length_row) == 1


def test_save_when_hint_word_invalid(opened: Opened) -> None:
    """空の語と区切りを含む語では保存せず、エラーを出す（異常系）。"""
    # 準備（プリセット 1 件目の 1 つ目の語を空にし、2 つ目の語を「A、B」にする）
    word_edits = _add_hint_preset(opened.window, name="開発", word_count=2)
    word_edits[1].setText("A、B")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    summary = _error_summary_text(opened.window)
    assert "プリセット 1 件目の 1 つ目の語: 語を入れるか、この欄を削除してください。" in summary
    assert (
        "プリセット 1 件目の 2 つ目の語: "
        "読点（、）・句点（。）・改行は入れられません。語を分けて追加してください。"
    ) in summary


def _edge_phrase_edit(window: SettingsWindow, text: str) -> QLineEdit:
    """「ハルシネーション」の文言の欄のうち、今の文字が text のものを返す。"""
    matches = [edit for edit in _visible_edits(window, "edge_phrase_text_") if edit.text() == text]
    assert len(matches) == 1, f"文言「{text}」の欄が 1 つでない"
    return matches[0]


def _edge_phrase_row_widget[T: QWidget](
    window: SettingsWindow, edit: QLineEdit, kind: type[T], prefix: str
) -> T:
    """文言の欄と同じ行（objectName の末尾の {n} が同じ）の、prefix で始まる部品を返す。"""
    row_id = edit.objectName().removeprefix("edge_phrase_text_")
    widget = window.findChild(kind, f"{prefix}{row_id}")
    assert widget is not None, f"{prefix}{row_id} が無い"
    return widget


def _move_edge_phrase_up(window: SettingsWindow, text: str) -> None:
    """今の文字が text の文言の欄に Alt+↑ を送信し、行を 1 つ上へ動かす。"""
    QTest.keyClick(
        _edge_phrase_edit(window, text), Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier
    )


def test_save_when_edge_phrases(opened: Opened) -> None:
    """文言の一覧を並びのまま設定に入れ、空の行を捨てて書く（正常系）。"""
    # 準備（「ハルシネーション」で行を 2 つ追加し、1 つ目に「お疲れ様でした」（文頭）を入れて先頭へ動かし、「ありがとうございました」の行を削除する）
    _select_group(opened.window, "ハルシネーション")
    _button(opened.window, "add_edge_phrase_button").click()
    _button(opened.window, "add_edge_phrase_button").click()
    new_edit = _visible_edits(opened.window, "edge_phrase_text_")[3]
    new_edit.setText("お疲れ様でした")
    _edge_phrase_row_widget(opened.window, new_edit, QComboBox, "edge_phrase_position_").setCurrentText(
        "文頭"
    )
    _move_edge_phrase_up(opened.window, "お疲れ様でした")
    _move_edge_phrase_up(opened.window, "お疲れ様でした")
    _move_edge_phrase_up(opened.window, "お疲れ様でした")
    removed_edit = _edge_phrase_edit(opened.window, "ありがとうございました")
    _edge_phrase_row_widget(
        opened.window, removed_edit, QAbstractButton, "edge_phrase_remove_"
    ).click()

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    saved_settings = opened.deps.save_settings.call_args.args[0]
    assert [(phrase.text, phrase.position) for phrase in saved_settings.edge_phrases] == [
        ("お疲れ様でした", "start"),
        ("チャンネル登録*", "end"),
        ("ご視聴ありがとうございました", "end"),
    ]


def test_save_when_edge_phrase_wildcard_only(opened: Opened) -> None:
    """`*` だけの文言では保存せず、エラーを出す（異常系）。"""
    # 準備（「ハルシネーション」の 2 行目の文言を「*」にする）
    _select_group(opened.window, "ハルシネーション")
    second_edit = _visible_edits(opened.window, "edge_phrase_text_")[1]
    second_edit.setText("*")

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is False
    opened.deps.save_settings.assert_not_called()
    assert (
        "ハルシネーションの 2 行目の文言: "
        "* だけの文言は、文頭・文末の行を丸ごと削除します。削除したい文言を入れてください。"
    ) in _error_summary_text(opened.window)
    assert second_edit.text() == "*"


def test_save_when_restart(opened: Opened) -> None:
    """「保存して再起動」は書いてから窓を閉じ、再起動を頼む（正常系）。"""
    # 準備
    saved_count: list[int] = []
    restart_count: list[int] = []
    closed_count: list[int] = []
    opened.window.saved.connect(lambda: saved_count.append(1))
    opened.window.restart_requested.connect(lambda: restart_count.append(1))
    opened.window.closed.connect(lambda: closed_count.append(1))
    _set_model(opened.window, "small")

    # 実行
    result = opened.window.save(restart=True)

    # 検証
    assert result is True
    assert saved_count == [1]
    assert restart_count == [1]
    assert closed_count == [1]


def _no_preset(window: SettingsWindow) -> None:
    """カスタムプリセットを追加しない（ホットキーを変える前の準備が要らないケース）。"""


def _add_browser_preset(window: SettingsWindow) -> None:
    """「ブラウザ添付」にカスタムプリセットを 1 件追加する（保存できるタイトルと URL を入れる）。"""
    _add_preset(window, "browser", title="A", url="https://a.example")


@pytest.mark.parametrize(
    ("group", "prepare", "hotkey_name", "expected_notice"),
    [
        pytest.param(
            "ホットキー",
            _no_preset,
            "hotkey_hotkeys.start",
            "保存しました。新しいホットキーは、設定画面を閉じると効きます。",
            id="recording_hotkey",
        ),
        pytest.param(
            "出力先",
            _no_preset,
            "hotkey_outputs[0].hotkey",
            "保存しました。新しいホットキーは、設定画面を閉じると効きます。",
            id="output_hotkey",
        ),
        pytest.param(
            "ブラウザ添付",
            _add_browser_preset,
            "preset_hotkey_0",
            "保存しました。新しいホットキーは、設定画面を閉じると効きます。",
            id="custom_preset_hotkey",
        ),
        pytest.param(
            "ホットキー", _no_preset, "hotkey_keyboard.paste_key", "保存しました。", id="paste_key"
        ),
    ],
)
def test_save_when_hotkey_changed(
    opened: Opened,
    group: str,
    prepare: Callable[[SettingsWindow], None],
    hotkey_name: str,
    expected_notice: str,
) -> None:
    """ホットキーを変えた保存では、閉じると効くことを添える（正常系）。"""
    # 準備（録音開始・出力先の確定・カスタムプリセットの確定のホットキーか、貼り付けに送信するキーだけを変える）
    _select_group(opened.window, group)
    prepare(opened.window)
    _press_hotkey(opened.window, hotkey_name)

    # 実行
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    assert _label(opened.window, "saved_notice").text() == expected_notice


def test_save_when_restart_field_changed(opened: Opened) -> None:
    """「再起動で反映」の欄を保存すると件数と今すぐ再起動を出し、保存の後に欄を変えると開いたときの値から数え直す（正常系）。"""
    # 準備
    _select_group(opened.window, "文字起こし")
    _set_model(opened.window, "small")

    # 実行（保存の直後と、続けて言語を変えた後を見る）
    result = opened.window.save(restart=False)
    saved_notice_text = _label(opened.window, "saved_notice").text()
    restart_now_visible = _button(opened.window, "restart_now_button").isVisible()
    restart_notice_visible = _label(opened.window, "restart_notice").isVisible()
    save_and_restart_visible = _button(opened.window, "save_and_restart_button").isVisible()
    _set_language(opened.window, "en")

    # 検証（保存の直後）
    assert result is True
    assert saved_notice_text == (
        "保存しました。「再起動で反映」の設定 1 件は、再起動するまで前の値で動きます。"
    )
    assert restart_now_visible
    assert not restart_notice_visible
    assert not save_and_restart_visible
    # 検証（言語を変えた後: 開いたときの値から 2 件を数え直す）
    assert not _label(opened.window, "saved_notice").isVisible()
    assert not _button(opened.window, "restart_now_button").isVisible()
    assert _label(opened.window, "restart_notice").isVisible()
    assert "を 2 件変えました" in _label(opened.window, "restart_notice").text()
    assert _button(opened.window, "save_and_restart_button").isVisible()


def test_save_when_glossary_reverted(
    open_with_glossaries: Callable[..., Opened], settings_model: type[Settings], tmp_path: Path
) -> None:
    """開いたままの 2 回目の保存で、開いたときの行へ戻した用語集も書き戻す（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（1 件目の用語集の行を 1 つオフにして保存する）
    first = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    second = GlossarySettings(name="会議用", path=tmp_path / "meeting.csv")
    opened = open_with_glossaries(
        [first, second],
        {
            first.path: [
                GlossaryEntry(wrong="あ", right="A"),
                GlossaryEntry(wrong="い", right="B"),
            ],
            second.path: [GlossaryEntry(wrong="う", right="C")],
        },
        settings=settings_model(glossaries=[first, second]),
    )
    _select_group(opened.window, "用語集")
    _visible_buttons(opened.window, "glossary_entry_on_")[0].click()
    opened.window.save(restart=False)

    # 実行（開いたまま、その行をオンに戻してもう一度保存する）
    _visible_buttons(opened.window, "glossary_entry_on_")[0].click()
    result = opened.window.save(restart=False)

    # 検証
    assert result is True
    assert opened.deps.save_settings.call_count == 2
    _, changed_rows = opened.deps.save_settings.call_args_list[1].args
    assert changed_rows == {
        first.path: [
            GlossaryEntry(wrong="あ", right="A"),
            GlossaryEntry(wrong="い", right="B"),
        ]
    }


def test_save_then_close(
    open_with_glossaries: Callable[..., Opened],
    settings_model: type[Settings],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保存の後に欄を変えずに閉じると確認を出さずに閉じ、保存の後に欄を変えると保存したメッセージが消える（正常系）。"""
    from voice_paste.shared.settings import GlossarySettings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（音量を変え、用語集の行を 1 つオフにして保存する。捨てる確認が出たら「捨てない」と回答する）
    confirm_discard = MagicMock(return_value=False)
    monkeypatch.setattr("voice_paste.ui.windows.settings_window.confirm_discard", confirm_discard)
    glossary = GlossarySettings(name="yogo", path=tmp_path / "yogo.csv")
    opened = open_with_glossaries(
        [glossary],
        {glossary.path: [GlossaryEntry(wrong="あ", right="A"), GlossaryEntry(wrong="い", right="B")]},
        settings=settings_model(glossaries=[glossary]),
    )
    closed_count: list[int] = []
    opened.window.closed.connect(lambda: closed_count.append(1))
    _select_group(opened.window, "用語集")
    _visible_buttons(opened.window, "glossary_entry_on_")[0].click()
    _select_group(opened.window, "録音")
    volume = _field(opened.window, "recording.volume_percent")
    assert isinstance(volume, QSlider)
    volume.setValue(NEW_VOLUME_PERCENT)
    opened.window.save(restart=False)
    hide_window = _field(opened.window, "recording.hide_window")
    assert isinstance(hide_window, QAbstractButton)

    # 実行（保存の後に欄を変えて知らせを見て、その欄を保存した値へ戻してから閉じる）
    hide_window.click()
    notice_visible_after_change = _label(opened.window, "saved_notice").isVisible()
    hide_window.click()
    result = opened.window.try_close()

    # 検証（音量と用語集の行の変更は保存した値が基準で、閉じるときに確認を出さない）
    assert not notice_visible_after_change
    assert result is True
    confirm_discard.assert_not_called()
    assert closed_count == [1]


# === collect ===


def test_collect_when_hidden_keys(
    qapp: QApplication, tmp_path: Path, settings_model: type[Settings]
) -> None:
    """出さないキーは欄を置かず、開いたときの値を返す（正常系）。"""
    from voice_paste.shared.settings import RecordingSettings
    from voice_paste.ui.windows.settings_window import SettingsWindow

    # 準備: 音量のキーを出さない設定で、既定と違う音量の値を入れて開く
    settings = settings_model(
        recording=RecordingSettings(lower_volume=False, volume_percent=40, fade_sec=1.5)
    )
    deps = make_ui_deps(tmp_path, settings=settings, hidden_setting_keys=frozenset(VOLUME_KEYS))
    window = SettingsWindow(deps)

    # 実行
    collected = window.collect()

    # 検証
    assert _existing_fields(window, VOLUME_KEYS) == []
    assert collected["recording"]["volume_percent"] == 40
    assert collected["recording"]["lower_volume"] is False
    assert collected["recording"]["fade_sec"] == 1.5


# === close_without_confirm ===


def test_close_without_confirm(opened: Opened, monkeypatch: pytest.MonkeyPatch) -> None:
    """欄を変えたままでも確認を出さずに閉じる（正常系）。"""
    # 準備: 欄を変え、捨てる確認が出たら「捨てない」と回答する
    confirm_discard = MagicMock(return_value=False)
    monkeypatch.setattr("voice_paste.ui.windows.settings_window.confirm_discard", confirm_discard)
    closed_count: list[int] = []
    opened.window.closed.connect(lambda: closed_count.append(1))
    volume = _field(opened.window, "recording.volume_percent")
    assert isinstance(volume, QSlider)
    volume.setValue(NEW_VOLUME_PERCENT)

    # 実行
    opened.window.close_without_confirm()

    # 検証
    confirm_discard.assert_not_called()
    assert closed_count == [1]
    opened.deps.save_settings.assert_not_called()


# === make_radio_group ===

THEME_CHOICES = ("system", "light", "dark")
THEME_LABELS = {"system": "Windows の設定に従う", "light": "ライト", "dark": "ダーク"}


def _radio_buttons(container: QWidget) -> list[QRadioButton]:
    """ラジオボタンの組のボタンを、並びの順で返す。"""
    return container.findChildren(QRadioButton)


def test_make_radio_group_when_labels(qapp: QApplication) -> None:
    """ボタンの名前を labels から出す（正常系）。"""
    from voice_paste.ui.windows.settings_fields import make_radio_group

    # 実行
    group = make_radio_group(THEME_CHOICES, "light", labels=THEME_LABELS)

    # 検証
    buttons = _radio_buttons(group)
    assert [button.text() for button in buttons] == ["Windows の設定に従う", "ライト", "ダーク"]
    assert [button.isChecked() for button in buttons] == [False, True, False]


def test_make_radio_group_when_no_labels(qapp: QApplication) -> None:
    """labels が無ければ値をそのまま名前にする（正常系）。"""
    from voice_paste.ui.windows.settings_fields import make_radio_group

    # 実行
    group = make_radio_group(("center", "top-left"), "center")

    # 検証
    buttons = _radio_buttons(group)
    assert [button.text() for button in buttons] == ["center", "top-left"]
    assert [button.isChecked() for button in buttons] == [True, False]


def test_make_radio_group_when_spacing(qapp: QApplication) -> None:
    """選択肢の間を choice_gap だけ空ける（正常系）。"""
    from voice_paste.ui.style import load_tokens
    from voice_paste.ui.windows.settings_fields import make_radio_group

    # 実行
    group = make_radio_group(("cuda", "cpu"), "cuda")

    # 検証
    layout = group.layout()
    assert layout is not None
    assert layout.spacing() == load_tokens()["shape"]["choice_gap"]


# === selected_radio ===


def test_selected_radio_when_labels(qapp: QApplication) -> None:
    """名前ではなく値を返す（正常系）。"""
    from voice_paste.ui.windows.settings_fields import make_radio_group, selected_radio

    # 準備: ラベル付きの組で「ダーク」を選ぶ
    group = make_radio_group(THEME_CHOICES, "light", labels=THEME_LABELS)
    dark = next(button for button in _radio_buttons(group) if button.text() == "ダーク")
    dark.setChecked(True)

    # 実行
    result = selected_radio(group)

    # 検証
    assert result == "dark"


# === format_hotkey ===


def test_format_hotkey() -> None:
    """修飾キーと文字を画面の表示形式にする（正常系）。"""
    from voice_paste.ui.windows.settings_window import format_hotkey

    # 実行・検証
    assert format_hotkey("<ctrl>+<alt>+d") == "Ctrl+Alt+D"
    assert format_hotkey("<ctrl>+<shift>+<f5>") == "Ctrl+Shift+F5"


def test_format_hotkey_when_cmd() -> None:
    """`<cmd>` を OS ごとの名前にする（正常系）。"""
    from voice_paste.shared.os_kind import OsKind
    from voice_paste.ui.windows.settings_window import format_hotkey

    # 実行・検証
    assert format_hotkey("<cmd>+<alt>+d", os_kind=OsKind.WINDOWS) == "Win+Alt+D"
    assert format_hotkey("<cmd>+<alt>+d", os_kind=OsKind.LINUX) == "Super+Alt+D"


# === parse_hotkey ===


def test_parse_hotkey() -> None:
    """押されたキーを pynput の書式にする（正常系）。"""
    from voice_paste.ui.windows.settings_window import parse_hotkey

    # 準備
    ctrl_alt_d = QKeyCombination(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier, Qt.Key.Key_D
    )
    ctrl_shift_f5 = QKeyCombination(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_F5
    )

    # 実行・検証
    assert parse_hotkey(ctrl_alt_d) == "<ctrl>+<alt>+d"
    assert parse_hotkey(ctrl_shift_f5) == "<ctrl>+<shift>+<f5>"


def test_parse_hotkey_when_modifier_only() -> None:
    """修飾キーだけは入れない（正常系）。"""
    from voice_paste.ui.windows.settings_window import parse_hotkey

    # 準備
    ctrl_only = QKeyCombination(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control)
    escape = QKeyCombination(Qt.Key.Key_Escape)

    # 実行・検証
    assert parse_hotkey(ctrl_only) is None
    assert parse_hotkey(escape) is None


# === to_field_message ===


def test_to_field_message_when_not_number(settings_model: type[Settings]) -> None:
    """数値でない文字（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            {"outputs": [{"id": "paste_and_send", "enter_delay_sec": "abc"}]}
        )

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == "数値を入れてください（例: 0.5）。"


def test_to_field_message_when_out_of_range(settings_model: type[Settings]) -> None:
    """範囲の外（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate({"api": {"port": 80}})

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == "1024〜65535 の値を入れてください。"


def test_to_field_message_when_preset_url_empty(settings_model: type[Settings]) -> None:
    """プリセットの URL が空（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            {"presets": [{"kind": "endpoint", "title": "受信先", "url": ""}]}
        )

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == "URL を入れてください（例: https://example.com/hook）。"


def test_to_field_message_when_openai_base_url_empty(settings_model: type[Settings]) -> None:
    """OpenAI の API の URL が空（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate({"transcription": {"openai": {"base_url": ""}}})

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == "API の URL を入れてください（例: https://api.openai.com/v1）。"


def test_to_field_message_when_hint_too_long(settings_model: type[Settings]) -> None:
    """有効なヒントが長すぎる（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備（有効な語をつないだ長さが 258 バイトの hint_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            {"hint_presets": [{"name": "開発", "words": ["あ" * 86], "enabled": True}]}
        )

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == (
        "有効なヒントが長すぎます（258 / 222 バイト）。語を減らすか、プリセットを無効にしてください。"
    )


def test_to_field_message_when_hint_preset_name_overlap(settings_model: type[Settings]) -> None:
    """表記のヒントのプリセットの名前が重なる（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備（名前が「開発」の 2 件の hint_presets）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            {"hint_presets": [{"name": "開発", "words": ["A"]}, {"name": "開発", "words": ["B"]}]}
        )

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == "プリセット「開発」と同じ名前です。別の名前にしてください。"


def test_to_field_message_when_web_origin_not_form(settings_model: type[Settings]) -> None:
    """形式の違う許す Origin（正常系）。"""
    from pydantic import ValidationError

    from voice_paste.ui.windows.settings_window import to_field_message

    # 準備（形式の違う 2 件の api.allowed_web_origins）
    with pytest.raises(ValidationError) as exc_info:
        settings_model.model_validate(
            {"api": {"allowed_web_origins": ["https://voice.example.com/", "voice.example.com"]}}
        )

    # 実行
    message = to_field_message(exc_info.value.errors()[0], model=settings_model)

    # 検証
    assert message == (
        "形式の違うオリジンがあります（https://voice.example.com/、voice.example.com）。"
        "https://example.com のように、http:// か https:// で始め、"
        "末尾の / とパスを付けずに入れてください。"
    )
