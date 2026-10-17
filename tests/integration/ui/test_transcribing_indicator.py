"""画面設計「文字起こし中の表示」を元にした結合テスト。

窓を出す・閉じる条件は、本物のトレイ・録音の画面とつないだ UiController の state_changed で確かめる。
出力先の切り替えのボタン・今の出力先の印・貼り付けの案内・プリセットの名前は、UiController の state_changed で確定した出力先を渡して開き、output_changed で替えて確かめる。
経過と残りの時間は、進められる時計を渡した文字起こし中の表示で確かめる。
切り替えのボタンの選んだ状態は QPushButton.isChecked() で確かめる。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, QRegularExpression, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QWidget

from tests.integration.ui.helpers import (
    FakeClock,
    Ui,
    button_texts,
    edge_and_face_colors,
    find,
    grab_head_row,
    make_ui_deps,
)
from voice_paste.main import SETTINGS_MODEL

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from PySide6.QtWidgets import QApplication

    from voice_paste.shared.settings import Preset, Settings
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

OUTPUT_IDS = ("paste_and_send", "paste_only", "copy_only")
"""設定の既定の並びの、固定の出力先の ID。"""

PASTE_HINT = "貼り付けたい場所にカーソルを合わせてください"
COPY_HINT = "起こした文字をクリップボードにコピーします"
"""貼り付けの案内の文（貼り付けて送信・貼り付けのみ / コピーのみ）。"""

SWITCH_WINDOW_MIN_WIDTH = 380
"""出力先の切り替えのボタンを出す回の窓の幅（画面設計の「ボタンが名前を省かずに収まる幅（既定 380px）」）。"""

BADGE_SAMPLE_FROM_RIGHT_PX = 5
BADGE_SAMPLE_FROM_TOP_PX = 12
"""今の出力先のボタンの右上の丸い印の、チェックの線を避けた円の内側の画素（ボタンの右端・上端からの距離）。"""


def _settings(**groups: object) -> Settings:
    """グループごとの設定（ui・outputs・hotkeys）を差し替えた設定を作る。"""
    return SETTINGS_MODEL(**groups)


def _opened(
    make_ui: Callable[..., Ui],
    settings: Settings | None = None,
    *,
    output_id: str = "paste_and_send",
    preset: Preset | None = None,
) -> Ui:
    """ホットキーの録音を確定した直後（transcribing）の、文字起こし中の表示を出した一式を返す。preset を渡すとカスタムプリセットで確定した回になる。"""
    ui = make_ui(settings)
    ui.notify_state(
        "hotkey",
        "transcribing",
        output_id=None if preset is not None else output_id,
        output_preset=preset,
    )
    return ui


def _switch_button(ui: Ui, output_id: str) -> QPushButton:
    """出力先の切り替えのボタンを引く。"""
    return find(ui.indicator, QPushButton, f"switch_button_{output_id}")


def _checked(ui: Ui) -> dict[str, bool]:
    """出力先ごとの、切り替えのボタンが選んだ状態かを返す。"""
    return {output_id: _switch_button(ui, output_id).isChecked() for output_id in OUTPUT_IDS}


def _name_and_key(button: QPushButton) -> tuple[QLabel, QLabel | None]:
    """ボタンの中の名前のラベルと、キー（role=keycap）のラベル（無ければ None）を返す。"""
    labels = button.findChildren(QLabel)
    keys = [label for label in labels if label.property("role") == "keycap"]
    names = [label for label in labels if label.property("role") != "keycap"]
    assert len(names) == 1
    return names[0], (keys[0] if keys else None)


@pytest.fixture
def clocked(qapp: QApplication, tmp_path: Path) -> Iterator[tuple[TranscribingIndicator, FakeClock]]:
    """進められる時計を渡した文字起こし中の表示を開いて返す。テストの後に閉じる。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    clock = FakeClock(0.0)
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=clock)
    indicator.open()
    yield indicator, clock
    indicator.close_window()


# === transcribing_indicator ===


@pytest.mark.parametrize(
    ("entry", "state", "hide_window", "shown"),
    [
        pytest.param("hotkey", "transcribing", False, True, id="hotkey_transcribing"),
        pytest.param("tray", "delivering", False, True, id="tray_delivering"),
        pytest.param("api", "transcribing", False, False, id="api_transcribing"),
        pytest.param("hotkey", "recording", False, False, id="hotkey_recording"),
        pytest.param("hotkey", "transcribing", True, False, id="hide_window"),
    ],
)
def test_transcribing_indicator_visible_when(
    make_ui: Callable[..., Ui], entry: str, state: str, hide_window: bool, shown: bool
) -> None:
    """ホットキー・トレイのセッションが transcribing か delivering の間だけ出る。画面を出さない設定・API の録音では出さない（表示条件）。"""
    from voice_paste.shared.settings import RecordingSettings, Settings

    # 準備
    ui = make_ui(Settings(recording=RecordingSettings(hide_window=hide_window)))

    # 実行
    ui.notify_state(entry, state)

    # 検証
    assert ui.indicator.isVisible() is shown


def test_transcribing_indicator_visible_when_idle(make_ui: Callable[..., Ui]) -> None:
    """届けた・結果が空で待機中に戻ると閉じる。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "transcribing")

    # 実行
    ui.notify_state(None)

    # 検証
    assert not ui.indicator.isVisible()


@pytest.mark.parametrize("topmost", [True, False], ids=["topmost_on", "topmost_off"])
def test_transcribing_indicator_does_not_take_focus(
    make_ui: Callable[..., Ui], topmost: bool
) -> None:
    """フォーカスを取らない（貼り付け先の入力欄からフォーカスを奪わない）。ui.topmost がオンなら最前面に残す。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(topmost=topmost)))

    # 実行
    ui.indicator.open()

    # 検証
    window = ui.indicator
    flags = window.windowFlags()
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is topmost


def test_transcribing_indicator_position(make_ui: Callable[..., Ui]) -> None:
    """録音の画面と同じ位置に出る（左上の位置なら、2 つの窓の左上が同じ）。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(position="top-left")))

    # 実行
    ui.recording_window.open()
    ui.indicator.open()

    # 検証
    assert ui.indicator.pos() == ui.recording_window.pos()


def test_transcribing_indicator_position_when_at(make_ui: Callable[..., Ui]) -> None:
    """座標を渡されたら、その座標に出る。"""
    # 実行
    ui = make_ui()
    ui.indicator.open(at=QPoint(300, 200))

    # 検証
    assert ui.indicator.pos() == QPoint(300, 200)


def test_transcribing_indicator_position_when_not_moved(make_ui: Callable[..., Ui]) -> None:
    """録音の画面を動かしていない回は、設定の位置（右下は作業領域の右下から 24px）に出る。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(position="bottom-right")))
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.notify_state("hotkey", "transcribing")

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    indicator = ui.indicator
    assert indicator.x() + indicator.width() == available.left() + available.width() - 24
    assert indicator.y() + indicator.height() == available.top() + available.height() - 24


def test_transcribing_indicator_position_when_only_pressed(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """録音の画面の見出しの行を押しただけで動かしていない回も、設定の位置に出る。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(position="bottom-right")))
    ui.notify_state("hotkey", "recording")
    grab_head_row(ui.recording_window)

    # 実行
    ui.notify_state("hotkey", "transcribing")

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    assert ui.indicator.x() + ui.indicator.width() == available.left() + available.width() - 24


def test_transcribing_indicator_position_when_moved(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """録音の画面を動かした回は、確定した時点の録音の画面の位置に出る。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    window = ui.recording_window
    grab_head_row(window)
    window.move(window.pos() + QPoint(80, 60))
    moved_to = window.pos()

    # 実行
    ui.notify_state("hotkey", "transcribing")

    # 検証
    assert ui.indicator.pos() == moved_to


def test_transcribing_indicator_position_when_moved_and_hidden(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """動かして隠したまま確定した回は、隠す前の位置に出る。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")
    window = ui.recording_window
    grab_head_row(window)
    window.move(window.pos() + QPoint(80, 60))
    moved_to = window.pos()
    ui.controller.hide_recording()

    # 実行
    ui.notify_state("hotkey", "transcribing")

    # 検証
    assert ui.indicator.pos() == moved_to


def test_transcribing_indicator_position_when_next_recording(
    make_ui: Callable[..., Ui], system_move: MagicMock
) -> None:
    """動かした位置はその回だけ使い、次の回の文字起こし中の表示は設定の位置に出る。"""
    from voice_paste.shared.settings import Settings, UiSettings

    # 準備
    ui = make_ui(Settings(ui=UiSettings(position="bottom-right")))
    ui.notify_state("hotkey", "recording")
    grab_head_row(ui.recording_window)
    ui.recording_window.move(ui.recording_window.pos() + QPoint(-200, -150))
    ui.notify_state("hotkey", "transcribing")
    ui.notify_state(None)
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.notify_state("hotkey", "transcribing")

    # 検証
    available = QGuiApplication.primaryScreen().availableGeometry()
    assert ui.indicator.x() + ui.indicator.width() == available.left() + available.width() - 24


# === state_label・paste_hint ===


def test_state_label(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """文字起こし中であることを、文字（文字起こし中）で出す。"""
    indicator, _ = clocked

    # 検証
    assert find(indicator, QLabel, "state_label").text() == "文字起こし中"


def test_paste_hint(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """貼り付けたい場所にカーソルを合わせるよう案内する。"""
    indicator, _ = clocked

    # 検証
    assert find(indicator, QLabel, "paste_hint").text() == "貼り付けたい場所にカーソルを合わせてください"


# === paste_hint（今の出力先の案内） ===


@pytest.mark.parametrize(
    ("output_id", "hint"),
    [
        pytest.param("paste_and_send", PASTE_HINT, id="paste_and_send"),
        pytest.param("paste_only", PASTE_HINT, id="paste_only"),
        pytest.param("copy_only", COPY_HINT, id="copy_only"),
    ],
)
def test_paste_hint_when_output(make_ui: Callable[..., Ui], output_id: str, hint: str) -> None:
    """今の出力先で何が起きるかを案内する。貼り付けて送信・貼り付けのみは貼り付ける場所の案内、コピーのみはクリップボードへコピーする案内。"""
    # 実行
    ui = _opened(make_ui, output_id=output_id)

    # 検証
    paste_hint = find(ui.indicator, QLabel, "paste_hint")
    assert paste_hint.isVisible()
    assert paste_hint.text() == hint


def test_paste_hint_when_switched(make_ui: Callable[..., Ui]) -> None:
    """出力先を切り替えると、案内の文を切り替えた先の文に変える。"""
    # 準備
    ui = _opened(make_ui, output_id="paste_and_send")

    # 実行
    ui.notify_output_changed("copy_only")

    # 検証
    assert find(ui.indicator, QLabel, "paste_hint").text() == COPY_HINT

    # 実行（貼り付けへ戻す）
    ui.notify_output_changed("paste_only")

    # 検証
    assert find(ui.indicator, QLabel, "paste_hint").text() == PASTE_HINT


def test_paste_hint_when_preset(make_ui: Callable[..., Ui]) -> None:
    """カスタムプリセットで確定した録音では、案内を出さない（プリセットはカーソルを合わせた場所へ貼らない）。"""
    from voice_paste.shared.settings import BrowserPreset

    # 実行
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))

    # 検証
    assert not find(ui.indicator, QLabel, "paste_hint").isVisible()


def test_paste_hint_when_reopened_after_preset(make_ui: Callable[..., Ui]) -> None:
    """カスタムプリセットで確定した回の次の、固定の出力先で確定した回では、案内を出し直す。"""
    from voice_paste.shared.settings import BrowserPreset

    # 準備
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))
    ui.notify_state(None)

    # 実行
    ui.notify_state("hotkey", "transcribing", output_id="copy_only")

    # 検証
    paste_hint = find(ui.indicator, QLabel, "paste_hint")
    assert paste_hint.isVisible()
    assert paste_hint.text() == COPY_HINT


# === head_row ===


def test_head_row_layout(make_ui: Callable[..., Ui]) -> None:
    """見出しの行に、左端のつかむ印と状態の表示を並べる。"""
    from voice_paste.ui.windows.window_parts import GripIcon

    # 実行
    ui = _opened(make_ui)

    # 検証
    row = find(ui.indicator, QWidget, "head_row")
    assert isinstance(row.layout().itemAt(0).widget(), GripIcon)
    assert row.isAncestorOf(find(ui.indicator, QLabel, "state_label"))


def test_head_row_cursor(make_ui: Callable[..., Ui]) -> None:
    """行にかざすと、カーソルが移動の形になる。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    assert find(ui.indicator, QWidget, "head_row").cursor().shape() == Qt.CursorShape.SizeAllCursor


@pytest.mark.parametrize("label", [None, "state_label"], ids=["blank", "state"])
def test_head_row_action(
    make_ui: Callable[..., Ui], system_move: MagicMock, label: str | None
) -> None:
    """行のどこをつかんでも（状態の表示の上を含む）、窓の移動を OS に任せる（ドラッグで窓を動かす）。"""
    # 準備
    ui = _opened(make_ui)
    row = find(ui.indicator, QWidget, "head_row")
    grabbed = row.rect().center()
    if label is not None:
        target = find(ui.indicator, QLabel, label)
        grabbed = target.mapTo(row, target.rect().center())

    # 実行
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=grabbed)

    # 検証
    system_move.assert_called_once_with()


def test_head_row_action_does_not_stop_time(
    clocked: tuple[TranscribingIndicator, FakeClock], system_move: MagicMock
) -> None:
    """動かしている間も文字起こしと経過は止めない（経過の表示は更新され、窓は出たまま）。"""
    indicator, clock = clocked
    row = find(indicator, QWidget, "head_row")

    # 実行
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
    QTest.mouseRelease(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
    clock.now = 2.0
    QTest.qWait(250)

    # 検証
    assert find(indicator, QLabel, "time_label").text() == "経過 2.0 秒 残りを計っています"
    assert indicator.isVisible()


# === output_heading ===


def test_output_heading(make_ui: Callable[..., Ui]) -> None:
    """今の出力先と切り替えの並びの見出し「出力先」を、常に出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    heading = find(ui.indicator, QLabel, "output_heading")
    assert heading.isVisible()
    assert heading.text() == "出力先"


def test_output_heading_when_preset(make_ui: Callable[..., Ui]) -> None:
    """カスタムプリセットで確定した回も、見出し「出力先」を出す。"""
    from voice_paste.shared.settings import BrowserPreset

    # 実行
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))

    # 検証
    assert find(ui.indicator, QLabel, "output_heading").isVisible()


# === switch_button_{output_id} ===


def test_switch_buttons_when_all_on(make_ui: Callable[..., Ui]) -> None:
    """オンの固定の出力先ごとに、設定の並びで 1 つずつ出し、名前の下にその出力先のホットキーを出す。"""
    # 実行
    ui = _opened(make_ui)

    # 検証
    assert button_texts(_switch_button(ui, "paste_and_send")) == ["貼り付けて送信", "Ctrl+Alt+D"]
    assert button_texts(_switch_button(ui, "paste_only")) == ["貼り付けのみ", "Ctrl+Alt+V"]
    assert button_texts(_switch_button(ui, "copy_only")) == ["コピーのみ", "Ctrl+Alt+C"]
    assert all(_switch_button(ui, output_id).isVisible() for output_id in OUTPUT_IDS)


def test_switch_buttons_when_some_off(make_ui: Callable[..., Ui]) -> None:
    """オフの出力先のボタンは出さない。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 実行
    ui = _opened(
        make_ui,
        _settings(
            outputs=[PasteAndSendSettings(), PasteOnlySettings(enabled=False), CopyOnlySettings()]
        ),
    )

    # 検証
    assert ui.indicator.findChild(QPushButton, "switch_button_paste_only") is None
    assert _switch_button(ui, "paste_and_send").isVisible()
    assert _switch_button(ui, "copy_only").isVisible()


def test_switch_buttons_order(make_ui: Callable[..., Ui]) -> None:
    """ボタンは、設定の並びで、左から右へ並べる。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 実行
    ui = _opened(
        make_ui,
        _settings(outputs=[CopyOnlySettings(), PasteAndSendSettings(), PasteOnlySettings()]),
    )

    # 検証
    buttons = ui.indicator.findChildren(QPushButton, QRegularExpression("^switch_button_"))
    assert [button.objectName() for button in sorted(buttons, key=lambda b: b.x())] == [
        "switch_button_copy_only",
        "switch_button_paste_and_send",
        "switch_button_paste_only",
    ]


def test_switch_buttons_width(apply_theme_to_app: Callable[[str], None], make_ui: Callable[..., Ui]) -> None:
    """ボタンは等しい幅で横に並べる。"""
    # 準備
    apply_theme_to_app("light")

    # 実行
    ui = _opened(make_ui)

    # 検証
    assert len({_switch_button(ui, output_id).width() for output_id in OUTPUT_IDS}) == 1


@pytest.mark.parametrize("output_id", OUTPUT_IDS)
def test_switch_buttons_when_current(make_ui: Callable[..., Ui], output_id: str) -> None:
    """今の出力先（確定で選んだもの）のボタンだけを選んだ状態にする。"""
    # 実行
    ui = _opened(make_ui, output_id=output_id)

    # 検証
    assert _checked(ui) == {key: key == output_id for key in OUTPUT_IDS}


def test_switch_button_badge_when_current(make_ui: Callable[..., Ui]) -> None:
    """今の出力先のボタンだけ、右上の角に丸い印（色だけで伝えない）を重ねる。"""
    from voice_paste.ui.style import theme_color

    # 実行
    ui = _opened(make_ui, output_id="paste_only")

    # 検証
    def sampled(output_id: str) -> QColor:
        """ボタンを描いた画像の、右上の丸い印の内側の画素の色を返す。"""
        button = _switch_button(ui, output_id)
        image = button.grab().toImage()
        return image.pixelColor(
            button.width() - BADGE_SAMPLE_FROM_RIGHT_PX, BADGE_SAMPLE_FROM_TOP_PX
        )

    assert sampled("paste_only") == theme_color("accent_fg")
    assert sampled("paste_and_send") != theme_color("accent_fg")
    assert sampled("copy_only") != theme_color("accent_fg")


def test_switch_buttons_when_preset(make_ui: Callable[..., Ui]) -> None:
    """カスタムプリセットで確定した録音では、切り替えのボタンを出さない。"""
    from voice_paste.shared.settings import BrowserPreset

    # 実行
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))

    # 検証
    buttons = ui.indicator.findChildren(QPushButton, QRegularExpression("^switch_button_"))
    assert [button for button in buttons if button.isVisible()] == []


def test_switch_buttons_when_reopened(make_ui: Callable[..., Ui]) -> None:
    """次の録音で出し直すと、ボタンと印をその回の確定した出力先で組み直す。"""
    # 準備
    ui = _opened(make_ui, output_id="paste_and_send")
    ui.notify_output_changed("copy_only")
    ui.notify_state(None)

    # 実行
    ui.notify_state("hotkey", "transcribing", output_id="paste_only")

    # 検証
    assert _checked(ui) == {"paste_and_send": False, "paste_only": True, "copy_only": False}


def test_switch_button_action(make_ui: Callable[..., Ui]) -> None:
    """今の出力先でないボタンを押すと、その出力先の ID で届ける出力先の差し替えを頼む。押しただけでは印を動かさない（差し替えが通るまで）。"""
    # 準備
    ui = _opened(make_ui, output_id="paste_and_send")

    # 実行
    QTest.mouseClick(_switch_button(ui, "copy_only"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.switch_output.assert_called_once_with("copy_only")
    assert _checked(ui) == {"paste_and_send": True, "paste_only": False, "copy_only": False}


def test_switch_button_action_when_current(make_ui: Callable[..., Ui]) -> None:
    """今の出力先のボタンを押しても、何もしない（差し替えを頼まず、印もそのまま）。"""
    # 準備
    ui = _opened(make_ui, output_id="paste_only")

    # 実行
    QTest.mouseClick(_switch_button(ui, "paste_only"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.switch_output.assert_not_called()
    assert _checked(ui) == {"paste_and_send": False, "paste_only": True, "copy_only": False}


def test_switch_button_action_when_output_changed(make_ui: Callable[..., Ui]) -> None:
    """差し替えが通って output_changed を受けると、今の出力先の印を切り替えた先のボタンへ移す。"""
    # 準備
    ui = _opened(make_ui, output_id="paste_and_send")

    # 実行
    QTest.mouseClick(_switch_button(ui, "copy_only"), Qt.MouseButton.LeftButton)
    ui.notify_output_changed("copy_only")

    # 検証
    assert _checked(ui) == {"paste_and_send": False, "paste_only": False, "copy_only": True}

    # 実行（切り替えた先を押し直しても何もしない）
    QTest.mouseClick(_switch_button(ui, "copy_only"), Qt.MouseButton.LeftButton)

    # 検証
    ui.deps.switch_output.assert_called_once_with("copy_only")
    assert _checked(ui) == {"paste_and_send": False, "paste_only": False, "copy_only": True}


def test_switch_buttons_when_delivering(make_ui: Callable[..., Ui]) -> None:
    """届け始めた後（delivering）の知らせでは、開き直さず、ボタンも印も変えない。"""
    # 準備
    ui = _opened(make_ui, output_id="paste_and_send")
    before = _switch_button(ui, "paste_and_send")

    # 実行
    ui.notify_state("hotkey", "delivering", output_id="paste_and_send")

    # 検証
    assert ui.indicator.isVisible()
    assert _switch_button(ui, "paste_and_send") is before
    assert _checked(ui) == {"paste_and_send": True, "paste_only": False, "copy_only": False}


@pytest.mark.parametrize("output_id", OUTPUT_IDS)
def test_switch_button_does_not_take_focus(make_ui: Callable[..., Ui], output_id: str) -> None:
    """ボタンを押しても窓は前面（アクティブ）にならず、ボタンもフォーカスを取らない（貼り付け先のフォーカスは動かない）。"""
    # 準備
    ui = _opened(make_ui)

    # 実行
    QTest.mouseClick(_switch_button(ui, output_id), Qt.MouseButton.LeftButton)

    # 検証
    assert not ui.indicator.isActiveWindow()
    assert _switch_button(ui, output_id).focusPolicy() == Qt.FocusPolicy.NoFocus


@pytest.mark.parametrize(
    ("output_id", "name"),
    [
        pytest.param("paste_and_send", "貼り付けて送信", id="paste_and_send"),
        pytest.param("paste_only", "貼り付けのみ", id="paste_only"),
        pytest.param("copy_only", "コピーのみ", id="copy_only"),
    ],
)
def test_switch_buttons_when_show_hotkeys_off(
    make_ui: Callable[..., Ui], output_id: str, name: str
) -> None:
    """ui.show_hotkeys がオフのとき、全てのボタンがホットキーを出さず、名前だけを出す。"""
    from voice_paste.shared.settings import UiSettings

    # 実行
    ui = _opened(make_ui, _settings(ui=UiSettings(show_hotkeys=False)))

    # 検証
    button = _switch_button(ui, output_id)
    assert _name_and_key(button)[1] is None
    assert button_texts(button) == [name]


def test_switch_buttons_when_show_hotkeys_off_then_reopened(make_ui: Callable[..., Ui]) -> None:
    """ui.show_hotkeys を切り替えた後に出す文字起こし中の表示から、ボタンの出し方が変わる（再起動は要らない）。"""
    from voice_paste.shared.settings import UiSettings

    # 準備
    ui = _opened(make_ui)
    assert _name_and_key(_switch_button(ui, "copy_only"))[1] is not None
    ui.notify_state(None)

    # 実行
    ui.deps.get_settings.return_value = _settings(ui=UiSettings(show_hotkeys=False))
    ui.notify_state("hotkey", "transcribing", output_id="paste_and_send")

    # 検証
    assert _name_and_key(_switch_button(ui, "copy_only"))[1] is None


def test_switch_buttons_when_hotkey_empty(
    apply_theme_to_app: Callable[[str], None], make_ui: Callable[..., Ui]
) -> None:
    """ホットキーが空の出力先は名前だけのボタンにし、同じ行のボタンと高さを揃えて、名前を上下の中央に置く。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings

    # 準備
    apply_theme_to_app("light")

    # 実行（貼り付けのみのホットキーを空にする）
    ui = _opened(
        make_ui,
        _settings(
            outputs=[PasteAndSendSettings(), PasteOnlySettings(hotkey=""), CopyOnlySettings()]
        ),
    )

    # 検証
    without_key = _switch_button(ui, "paste_only")
    with_key = _switch_button(ui, "paste_and_send")
    name_label, key_label = _name_and_key(without_key)
    assert key_label is None
    assert without_key.geometry().y() == with_key.geometry().y()
    assert without_key.height() == with_key.height()
    assert abs(name_label.geometry().center().y() - without_key.rect().center().y()) <= 1


def test_switch_buttons_fit_window(
    apply_theme_to_app: Callable[[str], None], make_ui: Callable[..., Ui]
) -> None:
    """切り替えのボタンを出す回の窓は、ボタンが名前とホットキーを省かずに収まる幅（380px 以上）にする。"""
    # 準備
    apply_theme_to_app("light")

    # 実行
    ui = _opened(make_ui)

    # 検証
    indicator = ui.indicator
    assert indicator.width() >= SWITCH_WINDOW_MIN_WIDTH
    for output_id in OUTPUT_IDS:
        button = _switch_button(ui, output_id)
        name_label, key_label = _name_and_key(button)
        assert key_label is not None
        assert name_label.fontMetrics().horizontalAdvance(name_label.text()) <= name_label.width()
        assert key_label.fontMetrics().horizontalAdvance(key_label.text()) <= key_label.width()
        assert indicator.rect().contains(button.mapTo(indicator, button.rect().topLeft()))
        assert indicator.rect().contains(button.mapTo(indicator, button.rect().bottomRight()))


def test_transcribing_indicator_width_when_preset(
    apply_theme_to_app: Callable[[str], None], make_ui: Callable[..., Ui]
) -> None:
    """カスタムプリセットで確定した回は、切り替えのボタンを出さないので、380px の幅にしない。"""
    from voice_paste.shared.settings import BrowserPreset

    # 準備
    apply_theme_to_app("light")

    # 実行
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))

    # 検証
    assert ui.indicator.width() < SWITCH_WINDOW_MIN_WIDTH


# === preset_label ===


def test_preset_label_when_preset(make_ui: Callable[..., Ui]) -> None:
    """カスタムプリセットで確定した録音で、確定したプリセットのタイトルを出す。"""
    from voice_paste.shared.settings import BrowserPreset

    # 実行
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))

    # 検証
    label = find(ui.indicator, QLabel, "preset_label")
    assert label.isVisible()
    assert label.text() == "ChatGPT"


def test_preset_label_when_fixed_output(make_ui: Callable[..., Ui]) -> None:
    """固定の出力先で確定した録音では、プリセットの名前を出さない。"""
    # 実行
    ui = _opened(make_ui, output_id="paste_and_send")

    # 検証
    assert not find(ui.indicator, QLabel, "preset_label").isVisible()


def test_preset_label_when_output_changed(make_ui: Callable[..., Ui]) -> None:
    """カスタムプリセットで確定した録音は切り替えを受けず、output_changed を受けても名前だけのまま。"""
    from voice_paste.shared.settings import BrowserPreset

    # 準備
    ui = _opened(make_ui, preset=BrowserPreset(title="ChatGPT", url="https://chatgpt.com"))

    # 実行
    ui.notify_output_changed("copy_only")

    # 検証
    assert find(ui.indicator, QLabel, "preset_label").text() == "ChatGPT"
    assert not find(ui.indicator, QLabel, "paste_hint").isVisible()


# === progress_bar ===


def test_progress_bar_when_no_progress(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """最初の区間の終わりが届くまでは、進みのバーを出さない（回る印だけ）。"""
    indicator, _ = clocked

    # 検証
    assert not find(indicator, QProgressBar, "progress_bar").isVisible()


def test_progress_bar_when_progressed(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """最初の区間の終わりが届いたら、整数の %（62）で出す。"""
    indicator, _ = clocked

    # 実行
    indicator.set_progress(3.1, 5.0)

    # 検証
    bar = find(indicator, QProgressBar, "progress_bar")
    assert bar.isVisible()
    assert bar.value() == 62


def test_progress_bar_when_reopened(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """次の録音で出し直すと、進みを隠して 0 から始める。"""
    indicator, _ = clocked
    indicator.set_progress(3.1, 5.0)

    # 実行
    indicator.close_window()
    indicator.open()

    # 検証
    bar = find(indicator, QProgressBar, "progress_bar")
    assert not bar.isVisible()
    assert bar.value() == 0


# === time_label ===


def test_time_label_when_no_progress(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """残りが分かるまでは「経過 1.4 秒 残りを計っています」と出す。"""
    indicator, clock = clocked

    # 実行
    clock.now = 1.4
    indicator.set_progress(0.0, 5.0)

    # 検証
    assert find(indicator, QLabel, "time_label").text() == "経過 1.4 秒 残りを計っています"


def test_time_label_when_progressed(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """経過と残りの時間・全体の時間を「経過 3.0 秒 残り 2 秒 / 5 秒」の形で出す。"""
    indicator, clock = clocked

    # 実行
    clock.now = 3.0
    indicator.set_progress(3.1, 5.0)

    # 検証
    assert find(indicator, QLabel, "time_label").text() == "経過 3.0 秒 残り 2 秒 / 5 秒"


def test_time_label_when_over_one_minute(clocked: tuple[TranscribingIndicator, FakeClock]) -> None:
    """1 分以上は「3 分 06 秒」の形で出す。"""
    indicator, clock = clocked

    # 実行（経過 186 秒、進み 1/2、全体 372 秒）
    clock.now = 186.0
    indicator.set_progress(186.0, 372.0)

    # 検証
    assert (
        find(indicator, QLabel, "time_label").text() == "経過 3 分 06 秒 残り 3 分 06 秒 / 6 分 12 秒"
    )


# === transcribing_indicator の配色 ===


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_transcribing_indicator_colors_when_theme(
    make_ui: Callable[..., Ui], apply_theme_to_app: Callable[[str], None], theme: str
) -> None:
    """窓の面は color.*.surface、外側の縁は color.*.frame の色で描く（録音の画面と同じ。* は ui.theme で決まる明暗）。"""
    from voice_paste.ui.style import load_tokens

    # 準備
    apply_theme_to_app(theme)
    ui = make_ui()
    ui.notify_state("hotkey", "transcribing")

    # 実行
    edge, face = edge_and_face_colors(ui.indicator)

    # 検証
    colors = load_tokens()["color"][theme]
    assert edge == QColor(colors["frame"])
    assert face == QColor(colors["surface"])
