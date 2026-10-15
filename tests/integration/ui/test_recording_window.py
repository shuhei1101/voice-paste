"""画面設計「録音の画面」を元にした結合テスト。

本物の録音の画面を offscreen で開き、UiDeps は差し替えた関数で受ける。
窓を出す・閉じる条件は、本物のトレイ・文字起こし中の表示とつないだ UiController の state_changed で確かめる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from tests.integration.ui.helpers import (
    Ui,
    button_texts,
    edge_and_face_colors,
    find,
    grab_head_row,
    no_modal,
)
from voice_paste.main import SETTINGS_MODEL
from voice_paste.ui.style import build_stylesheet, is_dark_theme

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Settings

PRESET_COLUMNS = 3
"""カスタムプリセットのボタンを横に並べる数（画面設計の「3 件ずつ横に並べて 4 件目から次の行へ折り返す」）。"""

WINDOW_MIN_WIDTH = 360
"""録音の画面の既定の幅（画面設計の「窓は既定の幅（360px）より狭くせず」）。"""

LONG_HOTKEY = "<ctrl>+<alt>+<shift>+<f12>"
LONG_HOTKEY_TEXT = "Ctrl+Alt+Shift+F12"
"""切れやすい長いホットキーの、設定の書式と画面の形。"""


def _opened(make_ui: Callable[..., Ui], settings: Settings | None = None) -> Ui:
    """録音の画面を開いた一式を返す。"""
    ui = make_ui(settings)
    ui.recording_window.open()
    return ui


def _settings(**groups: object) -> Settings:
    """グループごとの設定（recording・ui・outputs・hotkeys）を差し替えた設定を作る。"""
    return SETTINGS_MODEL(**groups)


@pytest.fixture
def styled(qapp: QApplication) -> Iterator[None]:
    """アプリのスタイルシート（tokens.toml から作る QSS）を当てる。ホットキーのキーの枠・余白の分も大きさに数えて確かめるため。"""
    before = qapp.styleSheet()
    qapp.setStyleSheet(build_stylesheet(is_dark_theme()))
    yield
    qapp.setStyleSheet(before)


def _name_and_key(button: QPushButton) -> tuple[QLabel, QLabel | None]:
    """ボタンの中の名前のラベルと、キー（role=keycap）のラベル（無ければ None）を返す。"""
    labels = button.findChildren(QLabel)
    keys = [label for label in labels if label.property("role") == "keycap"]
    names = [label for label in labels if label.property("role") != "keycap"]
    assert len(names) == 1
    return names[0], (keys[0] if keys else None)


def _assert_key_below_name(button: QPushButton, expected_key: str) -> None:
    """ホットキーが、名前の下（2 行目）のキーキャップで、ボタンの中に切れずに描かれることを確かめる。"""
    name_label, key_label = _name_and_key(button)
    assert key_label is not None
    assert key_label.text() == expected_key
    # 名前の下（2 行目）にある
    assert key_label.geometry().top() >= name_label.geometry().bottom()
    # ボタンの中に収まり、文字が切れない幅がある
    assert button.rect().contains(key_label.geometry())
    assert key_label.fontMetrics().horizontalAdvance(expected_key) <= key_label.width()


def _assert_inside_window(window: QWidget, button: QPushButton) -> None:
    """ボタン全体が窓の中に収まる（窓の端で切れない）ことを確かめる。"""
    assert window.rect().contains(button.mapTo(window, button.rect().topLeft()))
    assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))


# === recording_window ===


@pytest.mark.parametrize(
    ("entry", "state", "hide_window", "shown"),
    [
        pytest.param("hotkey", "recording", False, True, id="hotkey_recording"),
        pytest.param("hotkey", "paused", False, True, id="hotkey_paused"),
        pytest.param("tray", "recording", False, True, id="tray_recording"),
        pytest.param("api", "recording", False, False, id="api_recording"),
        pytest.param("hotkey", "transcribing", False, False, id="hotkey_transcribing"),
        pytest.param("hotkey", "recording", True, False, id="hide_window"),
    ],
)
def test_recording_window_visible_when(
    make_ui: Callable[..., Ui], entry: str, state: str, hide_window: bool, shown: bool
) -> None:
    """ホットキー・トレイから始めた録音の間だけ出る。画面を出さない設定・API の録音では出さない（表示条件）。"""
    from voice_paste.shared.settings import RecordingSettings

    # 準備
    ui = make_ui(_settings(recording=RecordingSettings(hide_window=hide_window)))

    # 実行
    ui.notify_state(entry, state)

    # 検証
    assert ui.recording_window.isVisible() is shown


def test_recording_window_visible_when_idle(make_ui: Callable[..., Ui]) -> None:
    """待機中に戻ると閉じる（確定・取り消しで閉じる）。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.notify_state(None)

    # 検証
    assert not ui.recording_window.isVisible()


@pytest.mark.parametrize("topmost", [True, False], ids=["topmost_on", "topmost_off"])
def test_recording_window_does_not_take_focus(
    make_ui: Callable[..., Ui], topmost: bool
) -> None:
    """出したときにフォーカスを取らない。ui.topmost がオンなら最前面に残す指定を足す（Tool・枠なし）。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = make_ui(_settings(ui=UiSettings(topmost=topmost)))

    # 実行
    ui.recording_window.open()

    # 検証
    window = ui.recording_window
    flags = window.windowFlags()
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is topmost


@pytest.mark.parametrize("follow_cursor", [True, False], ids=["follow_cursor", "primary"])
def test_recording_window_position_when_top_left(
    make_ui: Callable[..., Ui], follow_cursor: bool
) -> None:
    """設定のモニターの作業領域の、設定の位置（左上は端から 24px）に出る。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = make_ui(_settings(ui=UiSettings(position="top-left", follow_cursor=follow_cursor)))

    # 実行
    ui.recording_window.open()

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    window = ui.recording_window
    assert window.x() == available.left() + 24
    assert window.y() == available.top() + 24


def test_recording_window_position_when_bottom_right(make_ui: Callable[..., Ui]) -> None:
    """右下の位置は、作業領域の右下から 24px 離れる。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = make_ui(_settings(ui=UiSettings(position="bottom-right")))

    # 実行
    ui.recording_window.open()

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    window = ui.recording_window
    assert window.x() + window.width() == available.left() + available.width() - 24
    assert window.y() + window.height() == available.top() + available.height() - 24


# === state_label ===


def test_state_label_when_recording(make_ui: Callable[..., Ui]) -> None:
    """録音中は、赤の点と「録音中」の文字で出す（色だけで伝えない）。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    label = find(ui.recording_window, QLabel, "state_label")
    assert "録音中" in label.text()
    assert "●" in label.text()


def test_state_label_when_paused(make_ui: Callable[..., Ui]) -> None:
    """一時停止中は「一時停止中」の文字で出す。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    ui.recording_window.set_paused(True)

    # 検証
    assert "一時停止中" in find(ui.recording_window, QLabel, "state_label").text()


# === elapsed_label ===


def test_elapsed_label_when_opened(make_ui: Callable[..., Ui]) -> None:
    """出したときに 0 から数え、1 時間未満は mm:ss の形（00:00）で出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    assert find(ui.recording_window, QLabel, "elapsed_label").text() == "00:00"


def test_elapsed_label_when_running(make_ui: Callable[..., Ui]) -> None:
    """録音の間は経過時間が進む。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.qWait(1200)

    # 検証
    assert find(ui.recording_window, QLabel, "elapsed_label").text() == "00:01"


def test_elapsed_label_when_paused(make_ui: Callable[..., Ui]) -> None:
    """一時停止中は止めた時点のまま止まり、再開すると続きから進む。"""
    # 準備
    ui = _opened(make_ui)
    QTest.qWait(1200)
    ui.recording_window.set_paused(True)
    label = find(ui.recording_window, QLabel, "elapsed_label")
    paused_text = label.text()

    # 実行
    QTest.qWait(1200)
    still_paused_text = label.text()
    ui.recording_window.set_paused(False)
    QTest.qWait(1200)

    # 検証
    assert paused_text == "00:01"
    assert still_paused_text == "00:01"
    assert label.text() == "00:02"


def test_elapsed_label_format_when_over_one_hour() -> None:
    """1 時間以上は h:mm:ss の形（1:02:37）で出す。"""
    from voice_paste.ui.windows.recording_window import format_clock

    # 実行・検証
    assert format_clock(42_000) == "00:42"
    assert format_clock(3_757_000) == "1:02:37"


# === waveform ===


def test_waveform_when_recording(make_ui: Callable[..., Ui]) -> None:
    """録音中は音量を取り続け（UiDeps.level）、一時停止中は取らずに最後の形のまま出す。"""
    # 準備
    ui = _opened(make_ui)
    level = ui.deps.level
    QTest.qWait(300)
    calls_while_recording = level.call_count

    # 実行
    ui.recording_window.set_paused(True)
    calls_at_pause = level.call_count
    QTest.qWait(300)

    # 検証
    assert calls_while_recording > 0
    assert level.call_count == calls_at_pause
    assert find(ui.recording_window, QWidget, "waveform").isVisible()


# === pause_button・resume_button ===


def test_pause_button_when_recording(make_ui: Callable[..., Ui]) -> None:
    """録音中は一時停止のボタンだけを出し、名前の下に一時停止のホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    pause = find(window, QPushButton, "pause_button")
    assert pause.isVisible()
    assert button_texts(pause) == ["一時停止", "Ctrl+Alt+Z"]
    assert not find(window, QPushButton, "resume_button").isVisible()


def test_resume_button_when_paused(make_ui: Callable[..., Ui]) -> None:
    """一時停止中は、一時停止のボタンと同じ場所に再開のボタンを出し、同じホットキーを出す。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    ui.recording_window.set_paused(True)

    # 検証
    window = ui.recording_window
    resume = find(window, QPushButton, "resume_button")
    assert resume.isVisible()
    assert button_texts(resume) == ["再開", "Ctrl+Alt+Z"]
    assert not find(window, QPushButton, "pause_button").isVisible()


def test_pause_button_action(make_ui: Callable[..., Ui]) -> None:
    """一時停止のボタンは SessionManager.pause を、再開のボタンは resume を呼ぶ。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(find(ui.recording_window, QPushButton, "pause_button"), Qt.MouseButton.LeftButton)
    ui.recording_window.set_paused(True)
    QTest.mouseClick(find(ui.recording_window, QPushButton, "resume_button"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.pause.assert_called_once()
    ui.deps.resume.assert_called_once()


# === cancel_button ===


def test_cancel_button_label(make_ui: Callable[..., Ui]) -> None:
    """取り消しのボタンは常に出し、名前の下に取り消しのホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    cancel = find(ui.recording_window, QPushButton, "cancel_button")
    assert cancel.isVisible()
    assert button_texts(cancel) == ["取り消す", "Ctrl+Alt+Q"]


def test_cancel_button_action(make_ui: Callable[..., Ui]) -> None:
    """取り消しのボタンは録音を捨て（SessionManager.cancel）、窓を閉じる。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(find(ui.recording_window, QPushButton, "cancel_button"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.cancel.assert_called_once()
    assert not ui.recording_window.isVisible()


# === outputs_heading・output_button_{output_id} ===


def test_outputs_heading_when_outputs_on(make_ui: Callable[..., Ui]) -> None:
    """オンの出力先があっても、見出し「確定して届ける」を出さない。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    assert window.findChild(QLabel, "outputs_heading") is None
    assert find(window, QPushButton, "output_button_paste_and_send").isVisible()
    assert "確定して届ける" not in [label.text() for label in window.findChildren(QLabel)]


def test_outputs_heading_when_outputs_off(make_ui: Callable[..., Ui]) -> None:
    """出力先が全てオフでも、見出し「確定して届ける」を出さない。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 実行
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(enabled=False),
                PasteOnlySettings(enabled=False),
                CopyOnlySettings(enabled=False),
            ]
        ),
    )

    # 検証
    assert ui.recording_window.findChild(QLabel, "outputs_heading") is None


def test_output_buttons_when_all_on(make_ui: Callable[..., Ui]) -> None:
    """オンの出力先ごとに、設定の並びで 1 つずつ出し、名前の下にその出力先のホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "output_button_paste_and_send")) == [
        "貼り付けて送信",
        "Ctrl+Alt+D",
    ]
    assert button_texts(find(window, QPushButton, "output_button_paste_only")) == [
        "貼り付けのみ",
        "Ctrl+Alt+V",
    ]
    assert button_texts(find(window, QPushButton, "output_button_copy_only")) == [
        "コピーのみ",
        "Ctrl+Alt+C",
    ]


def test_output_buttons_when_some_off(make_ui: Callable[..., Ui]) -> None:
    """オフの出力先のボタンは出さない。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 実行
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(),
                PasteOnlySettings(enabled=False),
                CopyOnlySettings(),
            ]
        ),
    )

    # 検証
    window = ui.recording_window
    assert window.findChild(QPushButton, "output_button_paste_only") is None
    assert find(window, QPushButton, "output_button_paste_and_send").isVisible()
    assert find(window, QPushButton, "output_button_copy_only").isVisible()


def test_output_buttons_primary(make_ui: Callable[..., Ui]) -> None:
    """オンのうち一番上の出力先のボタンを、主の操作にする。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 実行（一番上の貼り付けて送信をオフにする）
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(enabled=False),
                PasteOnlySettings(),
                CopyOnlySettings(),
            ]
        ),
    )

    # 検証
    window = ui.recording_window
    assert find(window, QPushButton, "output_button_paste_only").property("primary") is True
    assert find(window, QPushButton, "output_button_copy_only").property("primary") is False


@pytest.mark.parametrize("paused", [False, True], ids=["recording", "paused"])
def test_output_button_action(make_ui: Callable[..., Ui], paused: bool) -> None:
    """出力先のボタンはその出力先の ID で録音を確定し、窓を閉じる。一時停止中でも確定できる。"""
    # 準備
    ui = _opened(make_ui)
    ui.recording_window.set_paused(paused)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "output_button_paste_only"),
        Qt.MouseButton.LeftButton,
    )

    # 検証
    ui.deps.complete.assert_called_once_with("paste_only", None)
    assert not ui.recording_window.isVisible()


# === presets_heading・preset_button_{n} ===


def _presets_settings(*presets: object) -> Settings:
    """カスタムプリセットを並べた Settings を作る。"""
    return _settings(presets=list(presets))


def _browser(title: str, hotkey: str = "", *, enabled: bool = True, url: str = "https://a.example") -> object:
    """ブラウザ添付のプリセットを作る。"""
    from voice_paste.shared.settings import BrowserPreset

    return BrowserPreset(title=title, url=url, hotkey=hotkey, enabled=enabled)


def _endpoint(title: str, hotkey: str = "", *, enabled: bool = True) -> object:
    """エンドポイントへ送るのプリセットを作る。"""
    from voice_paste.shared.settings import EndpointPreset

    return EndpointPreset(
        title=title, url="http://127.0.0.1:9000/hook", hotkey=hotkey, enabled=enabled
    )


def test_presets_heading_when_presets_enabled(make_ui: Callable[..., Ui]) -> None:
    """有効なプリセットが 1 つ以上あれば、見出し「カスタムプリセット」を出す。"""
    # 実行
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT")))

    # 検証
    heading = find(ui.recording_window, QLabel, "presets_heading")
    assert heading.isVisible()
    assert heading.text() == "カスタムプリセット"


def test_presets_heading_when_no_presets(make_ui: Callable[..., Ui]) -> None:
    """既定（プリセットが無い）なら、見出しもボタンも出さない。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    assert not find(window, QLabel, "presets_heading").isVisible()
    assert window.findChild(QPushButton, "preset_button_0") is None


def test_presets_heading_when_all_disabled(make_ui: Callable[..., Ui]) -> None:
    """有効なプリセットが 1 つも無ければ、見出しを出さない。"""
    # 実行
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT", enabled=False)))

    # 検証
    assert not find(ui.recording_window, QLabel, "presets_heading").isVisible()


def test_preset_buttons_order(make_ui: Callable[..., Ui]) -> None:
    """有効なプリセットごとに 1 つずつ、ブラウザ添付の並び → エンドポイントへ送るの並びの順に出し、名前の下にホットキーを出す。"""
    # 実行（設定の並びはエンドポイントが先。ボタンはブラウザ添付が先）
    ui = _opened(
        make_ui,
        _presets_settings(
            _endpoint("受け口", "<ctrl>+<alt>+4"),
            _browser("ChatGPT", "<ctrl>+<alt>+1"),
            _browser("Claude", "<ctrl>+<alt>+3"),
        ),
    )

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "preset_button_0")) == ["ChatGPT", "Ctrl+Alt+1"]
    assert button_texts(find(window, QPushButton, "preset_button_1")) == ["Claude", "Ctrl+Alt+3"]
    assert button_texts(find(window, QPushButton, "preset_button_2")) == ["受け口", "Ctrl+Alt+4"]


def test_preset_buttons_when_disabled(make_ui: Callable[..., Ui]) -> None:
    """無効なプリセットのボタンは出さない（残りは詰めて 0 から数える）。"""
    # 実行
    ui = _opened(
        make_ui,
        _presets_settings(_browser("ChatGPT", "<ctrl>+<alt>+1", enabled=False), _browser("Claude")),
    )

    # 検証
    window = ui.recording_window
    assert button_texts(find(window, QPushButton, "preset_button_0")) == ["Claude"]
    assert window.findChild(QPushButton, "preset_button_1") is None


def test_preset_buttons_when_hotkey_empty(make_ui: Callable[..., Ui]) -> None:
    """ホットキーが空のプリセットは、タイトルだけを出す。"""
    # 実行
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT")))

    # 検証
    assert button_texts(find(ui.recording_window, QPushButton, "preset_button_0")) == ["ChatGPT"]


def test_preset_buttons_wrap(make_ui: Callable[..., Ui]) -> None:
    """3 件ずつ横に並べ、4 件目から次の行へ折り返す（種類の境目でも行を変えない）。"""
    # 実行（ブラウザ添付 2 件 + エンドポイントへ送る 2 件）
    ui = _opened(
        make_ui,
        _presets_settings(_browser("A"), _browser("B"), _endpoint("C"), _endpoint("D")),
    )

    # 検証
    window = ui.recording_window
    positions = [
        (button.geometry().y(), button.geometry().x())
        for button in (find(window, QPushButton, f"preset_button_{n}") for n in range(4))
    ]
    first_row = {y for y, _x in positions[:PRESET_COLUMNS]}
    assert len(first_row) == 1
    assert positions[PRESET_COLUMNS][0] > positions[0][0]


def test_preset_button_when_title_is_long(make_ui: Callable[..., Ui]) -> None:
    """タイトルはボタンの幅で … に省略し、かざすと全体を出す。ホットキーは省略しない。"""
    # 実行
    long_title = "とても長い名前のプリセットのタイトルをここに書く"
    ui = _opened(make_ui, _presets_settings(_browser(long_title, "<ctrl>+<alt>+1")))

    # 検証
    button = find(ui.recording_window, QPushButton, "preset_button_0")
    title_text, hotkey_text = button_texts(button)
    assert title_text.endswith("…")
    assert title_text != long_title
    assert hotkey_text == "Ctrl+Alt+1"
    assert button.toolTip() == long_title


@pytest.mark.parametrize("paused", [False, True], ids=["recording", "paused"])
def test_preset_button_action(make_ui: Callable[..., Ui], paused: bool) -> None:
    """プリセットのボタンはそのプリセットで録音を確定し、窓を閉じる。一時停止中でも確定できる。"""
    # 準備
    claude = _browser("Claude", url="https://claude.ai/new")
    ui = _opened(make_ui, _presets_settings(_browser("ChatGPT"), claude))
    ui.recording_window.set_paused(paused)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "preset_button_1"), Qt.MouseButton.LeftButton
    )

    # 検証
    ui.deps.complete.assert_called_once_with(None, claude)
    assert not ui.recording_window.isVisible()


# === ボタンのホットキーの出し方（名前の下のキーキャップ・ボタンの大きさ・窓の幅） ===


def _long_hotkeys_settings(*, show_hotkeys: bool = True) -> Settings:
    """一時停止・取り消し・全ての出力先・プリセットのホットキーを、長いものにした設定を作る。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.shared.settings import HotkeySettings, UiSettings

    return _settings(
        ui=UiSettings(show_hotkeys=show_hotkeys),
        hotkeys=HotkeySettings(pause="<ctrl>+<alt>+<shift>+<f11>", cancel="<ctrl>+<alt>+<shift>+<f10>"),
        outputs=[
            PasteAndSendSettings(hotkey="<ctrl>+<alt>+<shift>+<f9>"),
            PasteOnlySettings(hotkey="<ctrl>+<alt>+<shift>+<f8>"),
            CopyOnlySettings(hotkey="<ctrl>+<alt>+<shift>+<f7>"),
        ],
        presets=[_browser("ChatGPT", LONG_HOTKEY)],
    )


@pytest.mark.parametrize(
    ("button_name", "expected_key"),
    [
        pytest.param("pause_button", "Ctrl+Alt+Shift+F11", id="pause"),
        pytest.param("cancel_button", "Ctrl+Alt+Shift+F10", id="cancel"),
        pytest.param("output_button_paste_and_send", "Ctrl+Alt+Shift+F9", id="paste_and_send"),
        pytest.param("output_button_paste_only", "Ctrl+Alt+Shift+F8", id="paste_only"),
        pytest.param("output_button_copy_only", "Ctrl+Alt+Shift+F7", id="copy_only"),
        pytest.param("preset_button_0", LONG_HOTKEY_TEXT, id="preset"),
    ],
)
def test_hotkey_buttons_key_below_name(
    styled: None, make_ui: Callable[..., Ui], button_name: str, expected_key: str
) -> None:
    """長いホットキーも、名前の下のキーキャップに、ボタンの中で切れずに出す。"""
    # 実行
    ui = _opened(make_ui, _long_hotkeys_settings())

    # 検証
    _assert_key_below_name(find(ui.recording_window, QPushButton, button_name), expected_key)


def test_hotkey_buttons_key_below_name_when_paused(styled: None, make_ui: Callable[..., Ui]) -> None:
    """一時停止中の再開のボタンも、長いホットキーを名前の下のキーキャップに、切れずに出す。"""
    # 準備
    ui = _opened(make_ui, _long_hotkeys_settings())

    # 実行
    ui.recording_window.set_paused(True)

    # 検証
    _assert_key_below_name(
        find(ui.recording_window, QPushButton, "resume_button"), "Ctrl+Alt+Shift+F11"
    )


def test_hotkey_buttons_when_hotkey_empty(styled: None, make_ui: Callable[..., Ui]) -> None:
    """ホットキーが空のプリセットのボタンは名前だけを出し、同じ行のボタンと高さを揃えて、名前を上下の中央に置く。"""
    # 実行（1 つ目はホットキーあり、2 つ目は空。同じ行に並ぶ）
    ui = _opened(
        make_ui, _presets_settings(_browser("ChatGPT", "<ctrl>+<alt>+1"), _browser("Claude"))
    )

    # 検証
    window = ui.recording_window
    with_key = find(window, QPushButton, "preset_button_0")
    without_key = find(window, QPushButton, "preset_button_1")
    name_label, key_label = _name_and_key(without_key)
    assert key_label is None
    assert without_key.geometry().y() == with_key.geometry().y()
    assert without_key.height() == with_key.height()
    assert abs(name_label.geometry().center().y() - without_key.rect().center().y()) <= 1


HOTKEY_BUTTONS = [
    pytest.param("pause_button", "一時停止", id="pause"),
    pytest.param("cancel_button", "取り消す", id="cancel"),
    pytest.param("output_button_paste_and_send", "貼り付けて送信", id="paste_and_send"),
    pytest.param("output_button_paste_only", "貼り付けのみ", id="paste_only"),
    pytest.param("output_button_copy_only", "コピーのみ", id="copy_only"),
    pytest.param("preset_button_0", "ChatGPT", id="preset"),
]
"""ホットキーを出す・出さないの設定が効く、録音の画面のボタン（再開は一時停止中に別に確かめる）。"""


@pytest.mark.parametrize(("button_name", "name"), HOTKEY_BUTTONS)
def test_hotkey_buttons_when_show_hotkeys_on(
    make_ui: Callable[..., Ui], button_name: str, name: str
) -> None:
    """ui.show_hotkeys がオンのとき、全てのボタンが名前の下にホットキーのキーキャップを出す。"""
    # 実行
    ui = _opened(make_ui, _long_hotkeys_settings(show_hotkeys=True))

    # 検証
    _name_label, key_label = _name_and_key(find(ui.recording_window, QPushButton, button_name))
    assert key_label is not None
    assert button_texts(find(ui.recording_window, QPushButton, button_name))[0] == name


@pytest.mark.parametrize(("button_name", "name"), HOTKEY_BUTTONS)
def test_hotkey_buttons_when_show_hotkeys_off(
    make_ui: Callable[..., Ui], button_name: str, name: str
) -> None:
    """ui.show_hotkeys がオフのとき、全てのボタンがホットキーを出さず、名前だけを出す。"""
    # 実行
    ui = _opened(make_ui, _long_hotkeys_settings(show_hotkeys=False))

    # 検証
    button = find(ui.recording_window, QPushButton, button_name)
    _name_label, key_label = _name_and_key(button)
    assert key_label is None
    assert button_texts(button) == [name]


def test_hotkey_buttons_when_show_hotkeys_off_and_paused(make_ui: Callable[..., Ui]) -> None:
    """ui.show_hotkeys がオフのとき、一時停止中の再開のボタンもホットキーを出さず、名前だけを出す。"""
    # 準備
    ui = _opened(make_ui, _long_hotkeys_settings(show_hotkeys=False))

    # 実行
    ui.recording_window.set_paused(True)

    # 検証
    resume = find(ui.recording_window, QPushButton, "resume_button")
    _name_label, key_label = _name_and_key(resume)
    assert key_label is None
    assert button_texts(resume) == ["再開"]


def test_hotkey_buttons_when_show_hotkeys_off_keeps_layout(
    styled: None, make_ui: Callable[..., Ui]
) -> None:
    """ui.show_hotkeys がオフのとき、名前だけのボタンは同じ行で高さが揃い、名前を上下の中央に置く。"""
    # 実行
    ui = _opened(make_ui, _long_hotkeys_settings(show_hotkeys=False))

    # 検証
    window = ui.recording_window
    pause = find(window, QPushButton, "pause_button")
    cancel = find(window, QPushButton, "cancel_button")
    name_label, _key_label = _name_and_key(pause)
    assert pause.height() == cancel.height()
    assert abs(name_label.geometry().center().y() - pause.rect().center().y()) <= 1
    for name in ("pause_button", "cancel_button", "output_button_paste_and_send", "preset_button_0"):
        _assert_inside_window(window, find(window, QPushButton, name))


def test_hotkey_buttons_when_show_hotkeys_off_then_reopened(make_ui: Callable[..., Ui]) -> None:
    """ui.show_hotkeys を切り替えた後に出す録音の画面から、ボタンの出し方が変わる（再起動は要らない）。"""
    # 準備
    ui = _opened(make_ui, _long_hotkeys_settings(show_hotkeys=True))
    assert _name_and_key(find(ui.recording_window, QPushButton, "pause_button"))[1] is not None
    ui.recording_window.close_window()

    # 実行
    ui.deps.get_settings.return_value = _long_hotkeys_settings(show_hotkeys=False)
    ui.recording_window.open()
    # 組み直しで外した古いボタンの破棄を済ませる
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    # 検証
    pause = find(ui.recording_window, QPushButton, "pause_button")
    assert _name_and_key(pause)[1] is None


def test_hotkey_buttons_height_when_in_same_row(styled: None, make_ui: Callable[..., Ui]) -> None:
    """一時停止と取り消しのボタンは、同じ行で同じ高さにそろい、名前とキーの 2 行が入る高さがある。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    window = ui.recording_window
    pause = find(window, QPushButton, "pause_button")
    cancel = find(window, QPushButton, "cancel_button")
    name_label, key_label = _name_and_key(pause)
    assert key_label is not None
    assert pause.height() == cancel.height()
    assert pause.height() >= name_label.height() + key_label.height()


def test_hotkey_buttons_width_when_preset_columns(styled: None, make_ui: Callable[..., Ui]) -> None:
    """プリセットのボタンの幅は、列ごとにいちばん広いボタンにそろう。"""
    # 実行（1 列目は短いホットキーと長いホットキー）
    ui = _opened(
        make_ui,
        _presets_settings(
            _browser("A", "<ctrl>+<alt>+1"),
            _browser("B"),
            _browser("C"),
            _browser("D", LONG_HOTKEY),
        ),
    )

    # 検証
    window = ui.recording_window
    first_row = find(window, QPushButton, "preset_button_0")
    second_row = find(window, QPushButton, "preset_button_3")
    assert first_row.width() == second_row.width()
    assert first_row.width() >= _name_and_key(second_row)[1].width()


def test_recording_window_width_when_narrow(styled: None, make_ui: Callable[..., Ui]) -> None:
    """ボタンが要る幅が既定の幅（360px）より狭いときは、窓を 360px にする。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 実行（出力先もプリセットも出さず、一時停止と取り消しだけ）
    ui = _opened(
        make_ui,
        _settings(
            outputs=[
                PasteAndSendSettings(enabled=False),
                PasteOnlySettings(enabled=False),
                CopyOnlySettings(enabled=False),
            ]
        ),
    )

    # 検証
    assert ui.recording_window.width() == WINDOW_MIN_WIDTH


def test_recording_window_width_when_wide(styled: None, make_ui: Callable[..., Ui]) -> None:
    """ボタンが要る幅が既定の幅を超えるときは、その幅まで窓を広げ、ボタンを窓の端で切らない。"""
    # 実行（長いホットキーのプリセットを 3 件、1 行に並べる）
    ui = _opened(
        make_ui,
        _presets_settings(
            _browser("A", "<ctrl>+<alt>+<shift>+<f12>"),
            _browser("B", "<ctrl>+<alt>+<shift>+<f11>"),
            _browser("C", "<ctrl>+<alt>+<shift>+<f10>"),
        ),
    )

    # 検証
    window = ui.recording_window
    assert window.width() > WINDOW_MIN_WIDTH
    _assert_inside_window(window, find(window, QPushButton, "preset_button_0"))
    _assert_inside_window(window, find(window, QPushButton, "preset_button_1"))
    _assert_inside_window(window, find(window, QPushButton, "preset_button_2"))


def test_recording_window_width_when_reopened(styled: None, make_ui: Callable[..., Ui]) -> None:
    """前の録音で広がった幅を、次の録音の窓へ持ち越さない（ボタンが要る幅へ戻す）。"""
    # 準備（長いホットキーで広げて閉じる）
    ui = _opened(
        make_ui,
        _presets_settings(
            _browser("A", "<ctrl>+<alt>+<shift>+<f12>"),
            _browser("B", "<ctrl>+<alt>+<shift>+<f11>"),
            _browser("C", "<ctrl>+<alt>+<shift>+<f10>"),
        ),
    )
    assert ui.recording_window.width() > WINDOW_MIN_WIDTH
    ui.recording_window.close_window()

    # 実行（出力先もプリセットも無い設定で開き直す）
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    ui.deps.get_settings.return_value = _settings(
        outputs=[
            PasteAndSendSettings(enabled=False),
            PasteOnlySettings(enabled=False),
            CopyOnlySettings(enabled=False),
        ]
    )
    ui.recording_window.open()

    # 検証
    assert ui.recording_window.width() == WINDOW_MIN_WIDTH


# === head_row ===


def test_head_row_layout(make_ui: Callable[..., Ui]) -> None:
    """見出しの行に、左端のつかむ印・状態の表示・経過時間・隠すと×のボタンを並べる。"""
    from voice_paste.ui.windows.recording_window import GripIcon

    # 実行
    ui = _opened(make_ui)

    # 検証
    row = find(ui.recording_window, QWidget, "head_row")
    assert isinstance(row.layout().itemAt(0).widget(), GripIcon)
    for name, cls in (
        ("state_label", QLabel),
        ("elapsed_label", QLabel),
        ("hide_button", QPushButton),
        ("close_button", QPushButton),
    ):
        assert row.isAncestorOf(find(ui.recording_window, cls, name))


def test_head_row_cursor(make_ui: Callable[..., Ui]) -> None:
    """行にかざすと、カーソルが移動の形になる。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    row = find(ui.recording_window, QWidget, "head_row")
    assert row.cursor().shape() == Qt.CursorShape.SizeAllCursor


@pytest.mark.parametrize(
    "label", [None, "state_label", "elapsed_label"], ids=["blank", "state", "elapsed"]
)
def test_head_row_action(
    make_ui: Callable[..., Ui], system_move: MagicMock, label: str | None
) -> None:
    """行のどこをつかんでも（状態の表示・経過時間の上を含む）、窓の移動を OS に任せる（ドラッグで窓を動かす）。"""
    # 準備
    ui = _opened(make_ui)
    row = find(ui.recording_window, QWidget, "head_row")
    grabbed = row.rect().center()
    if label is not None:
        target = find(ui.recording_window, QLabel, label)
        grabbed = target.mapTo(row, target.rect().center())

    # 実行
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=grabbed)

    # 検証
    system_move.assert_called_once_with()


def test_head_row_action_when_buttons_pressed(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """隠す・× の上はつかめない（押しても窓の移動を始めない）。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "hide_button"), Qt.MouseButton.LeftButton
    )
    ui.recording_window.open()
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "close_button"), Qt.MouseButton.LeftButton
    )

    # 検証
    system_move.assert_not_called()


def test_head_row_action_does_not_stop_recording(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """動かしている間も録音と経過時間は止めない。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    grab_head_row(ui.recording_window)
    QTest.qWait(1200)

    # 検証
    assert find(ui.recording_window, QLabel, "elapsed_label").text() == "00:01"
    ui.deps.pause.assert_not_called()
    ui.deps.cancel.assert_not_called()
    assert ui.recording_window.isVisible()


def test_moved_position_when_dragged(make_ui: Callable[..., Ui], system_move: MagicMock) -> None:
    """窓を動かした回は、放した位置を返す。"""
    # 準備
    ui = _opened(make_ui)
    window = ui.recording_window
    grab_head_row(window)

    # 実行
    window.move(window.pos() + QPoint(60, 40))

    # 検証
    assert window.moved_position() == window.pos()


def test_moved_position_when_not_grabbed(make_ui: Callable[..., Ui]) -> None:
    """見出しの行をつかんでいない回は、None を返す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    assert ui.recording_window.moved_position() is None


def test_moved_position_when_only_pressed(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """見出しの行を押しただけで位置が変わらない回は、None を返す。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    grab_head_row(ui.recording_window)

    # 検証
    assert ui.recording_window.moved_position() is None


def test_moved_position_when_shifted_after_open(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """出した後に OS が窓の位置をずらしても、つかんだだけの回は None を返す。"""
    # 準備
    ui = _opened(make_ui)
    window = ui.recording_window
    window.move(window.pos() + QPoint(8, 8))

    # 実行
    grab_head_row(window)

    # 検証
    assert window.moved_position() is None


def test_moved_position_when_reopened(make_ui: Callable[..., Ui], system_move: MagicMock) -> None:
    """動かした位置はその回だけ使い、次の録音は設定の位置に出す。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = _opened(make_ui, _settings(ui=UiSettings(position="top-left")))
    window = ui.recording_window
    grab_head_row(window)
    window.move(window.pos() + QPoint(120, 90))
    window.close_window()

    # 実行
    window.open()

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    assert window.pos() == QPoint(available.left() + 24, available.top() + 24)
    assert window.moved_position() is None


# === hide_button ===


def test_hide_button_label(make_ui: Callable[..., Ui]) -> None:
    """かざすと戻し方を添えた説明を出す。録音開始と同じホットキーの出力先がある設定（既定）では、トレイのアイコンで戻す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    hide = find(ui.recording_window, QPushButton, "hide_button")
    assert hide.toolTip() == "録音の画面を隠す（トレイのアイコンで戻す）"
    assert hide.accessibleName() == "録音の画面を隠す"


def test_hide_button_label_when_start_hotkey_is_free(make_ui: Callable[..., Ui]) -> None:
    """録音開始と同じホットキーの出力先が無い設定では、トレイのアイコンか録音開始のホットキーで戻すと添える。"""
    from voice_paste.shared.settings import HotkeySettings

    # 実行
    ui = _opened(make_ui, _settings(hotkeys=HotkeySettings(start="<ctrl>+<alt>+r")))

    # 検証
    hide = find(ui.recording_window, QPushButton, "hide_button")
    assert hide.toolTip() == "録音の画面を隠す（トレイのアイコンか Ctrl+Alt+R で戻す）"


def test_hide_button_action(make_ui: Callable[..., Ui]) -> None:
    """その回だけ録音の画面を隠す。セッションの状態・録音は止めず、確定・一時停止・取り消しを呼ばない。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")

    # 実行
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "hide_button"), Qt.MouseButton.LeftButton
    )

    # 検証
    assert not ui.recording_window.isVisible()
    ui.deps.pause.assert_not_called()
    ui.deps.cancel.assert_not_called()
    ui.deps.complete.assert_not_called()


def test_hide_button_action_then_next_recording(make_ui: Callable[..., Ui]) -> None:
    """隠すのはその回だけで、次の録音ではいつもどおり出す。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    QTest.mouseClick(
        find(ui.recording_window, QPushButton, "hide_button"), Qt.MouseButton.LeftButton
    )
    ui.notify_state(None)

    # 実行
    ui.notify_state("hotkey", "recording")

    # 検証
    assert ui.recording_window.isVisible()


def test_hide_button_action_when_paused_while_hidden(make_ui: Callable[..., Ui]) -> None:
    """隠している間に一時停止しても、窓は出さない。戻すと一時停止中を示し、経過時間は一時停止した時点で止まっている。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    QTest.qWait(1200)
    ui.controller.hide_recording()
    QTest.qWait(1200)

    # 実行
    ui.notify_state("hotkey", "paused")
    hidden_after_pause = not ui.recording_window.isVisible()
    QTest.qWait(1200)
    ui.controller.show_recording()

    # 検証
    window = ui.recording_window
    assert hidden_after_pause
    assert window.isVisible()
    assert "一時停止中" in find(window, QLabel, "state_label").text()
    assert find(window, QLabel, "elapsed_label").text() == "00:02"


def test_hide_button_action_then_restore(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """隠した画面を戻すと、隠す前の位置に、経過時間と状態を保ったまま出る。窓の作りはフォーカスを取らない出し方のまま。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    window = ui.recording_window
    grab_head_row(window)
    window.move(window.pos() + QPoint(70, 50))
    moved_to = window.pos()
    QTest.qWait(1200)
    ui.controller.hide_recording()
    QTest.qWait(1200)

    # 実行
    ui.controller.show_recording()

    # 検証
    assert window.isVisible()
    assert window.pos() == moved_to
    assert find(window, QLabel, "elapsed_label").text() == "00:02"
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_hide_button_action_when_hide_window_setting(make_ui: Callable[..., Ui]) -> None:
    """画面を出さない設定の録音では、戻す操作をしても窓を出さない。"""
    from voice_paste.shared.settings import RecordingSettings

    # 準備
    ui = make_ui(_settings(recording=RecordingSettings(hide_window=True)))
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.controller.show_recording()

    # 検証
    assert not ui.recording_window.isVisible()


# === close_button ===


def test_close_button_label(make_ui: Callable[..., Ui]) -> None:
    """かざすと「取り消す」と取り消しのホットキーを添えた説明を出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    close = find(ui.recording_window, QPushButton, "close_button")
    assert close.toolTip() == "取り消す（Ctrl+Alt+Q）"
    assert close.accessibleName() == "取り消す"


def test_close_button_action(make_ui: Callable[..., Ui]) -> None:
    """「取り消す」のボタンと同じく録音を捨て（SessionManager.cancel）、窓を閉じる。確認は挟まない。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    with no_modal():
        QTest.mouseClick(
            find(ui.recording_window, QPushButton, "close_button"), Qt.MouseButton.LeftButton
        )

    # 検証
    ui.deps.cancel.assert_called_once()
    ui.deps.complete.assert_not_called()
    assert not ui.recording_window.isVisible()


# === recording_window の配色 ===


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_recording_window_colors_when_theme(
    make_ui: Callable[..., Ui], apply_theme_to_app: Callable[[str], None], theme: str
) -> None:
    """窓の面は color.*.surface、外側の縁は color.*.frame の色で描く（* は ui.theme で決まる明暗）。"""
    from voice_paste.ui.style import load_tokens

    # 準備
    apply_theme_to_app(theme)
    ui = make_ui()
    ui.notify_state("hotkey", "recording")

    # 実行
    edge, face = edge_and_face_colors(ui.recording_window)

    # 検証
    colors = load_tokens()["color"][theme]
    assert edge == QColor(colors["frame"])
    assert face == QColor(colors["surface"])
