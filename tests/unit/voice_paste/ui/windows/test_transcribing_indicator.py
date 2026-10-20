"""ui/windows/transcribing_indicator.py（TranscribingIndicator の open・set_progress・set_output）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。経過は進められる時計に差し替える。
欄は画面設計の項目 ID（progress_bar・time_label・paste_hint・preset_label・switch_button_{output_id}）の objectName で引く。
切り替えのボタンの選んだ状態は QPushButton.isChecked() で確かめる。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRect, QRegularExpression, QSize, Qt
from PySide6.QtGui import QFontMetrics, QImage
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton

from tests.unit.voice_paste.ui.helpers import OUTPUT_TITLES, FakeClock, make_ui_deps

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication, QWidget

    from voice_paste.shared.settings import Settings

SWITCH_BUTTON_PATTERN = QRegularExpression("^switch_button_")
"""切り替えのボタンの objectName に当てる正規表現。"""

ALL_OUTPUT_IDS = ("paste_and_send", "paste_only", "copy_only")
"""切り替えのボタンを 3 つ出す回にオンにする出力先の ID。"""

TWO_OUTPUT_IDS = ("paste_only", "copy_only")
"""切り替えのボタンを 2 つ出す回にオンにする出力先の ID。"""

PREVIOUS_WINDOW_WIDTH_PX = 800
"""前の回に窓を広げた幅（切り替えのボタンの幅が引き継がれないことを確かめる、どのボタンの合計よりも広い値）。"""

SHOW_HOTKEYS_CASES = [
    pytest.param(True, id="hotkeys_on"),
    pytest.param(False, id="hotkeys_off"),
]
"""`ui.transcribing_show_hotkeys` の両方の値。"""


def test_open_when_window_role(qapp: QApplication, tmp_path: Path) -> None:
    """窓の外側の枠の role が window（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=FakeClock(0.0))

    # 実行
    indicator.open()

    # 検証
    outer_frames = indicator.findChildren(QFrame, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert [frame.property("role") for frame in outer_frames] == ["window"]


def test_open_when_preset(qapp: QApplication, tmp_path: Path) -> None:
    """カスタムプリセットで確定したときは名前だけを出す（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=FakeClock(0.0))

    # 実行
    indicator.open(preset_title="ChatGPT")

    # 検証
    preset_label = indicator.findChild(QLabel, "preset_label")
    switch_buttons = indicator.findChildren(QPushButton, QRegularExpression("^switch_button_"))
    paste_hints = indicator.findChildren(QLabel, "paste_hint")
    assert preset_label.text() == "ChatGPT"
    assert [button for button in switch_buttons if button.isVisible()] == []
    assert [hint for hint in paste_hints if hint.isVisible()] == []


# === 切り替えのボタンの幅 ===


def _switch_settings(show_hotkeys: bool, enabled_ids: tuple[str, ...]) -> Settings:
    """enabled_ids の出力先だけをオンにし、文字起こし中の表示のホットキーを出すかを show_hotkeys にした設定を作る。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.main import SETTINGS_MODEL
    from voice_paste.shared.settings import UiSettings

    return SETTINGS_MODEL(
        ui=UiSettings(show_hotkeys=True, transcribing_show_hotkeys=show_hotkeys),
        outputs=[
            PasteAndSendSettings(enabled="paste_and_send" in enabled_ids),
            PasteOnlySettings(enabled="paste_only" in enabled_ids),
            CopyOnlySettings(enabled="copy_only" in enabled_ids),
        ],
    )


def _switch_buttons(indicator: QWidget) -> list[QPushButton]:
    """表示に並んだ切り替えのボタンを返す。"""
    return indicator.findChildren(QPushButton, SWITCH_BUTTON_PATTERN)


def _fixed_widths(buttons: list[QPushButton]) -> set[tuple[int, int]]:
    """ボタンごとの（minimumWidth, maximumWidth）の組を、重なりを除いて返す。"""
    return {(button.minimumWidth(), button.maximumWidth()) for button in buttons}


def _widest_hint(buttons: list[QPushButton]) -> int:
    """ボタンの sizeHint の幅のうち最も大きい値を返す。"""
    return max(button.sizeHint().width() for button in buttons)


def _widen_from_minimum(qapp: QApplication, indicator: QWidget, widen_px: int) -> None:
    """窓を minimumSizeHint の幅から widen_px だけ広げ、幅の変更で起きる組み直しまで済ませる。"""
    minimum = indicator.minimumSizeHint()
    indicator.resize(minimum.width() + widen_px, minimum.height())
    qapp.processEvents()


def _free_space_right_of_last(indicator: QWidget, buttons: list[QPushButton]) -> int:
    """最後のボタンの右に残る空きの幅（px）を返す。行の右端は、同じ枠に縦に並んで枠の幅いっぱいに置かれる出力先の見出しの右端で見る（どちらも枠の子なので座標をそのまま比べる）。"""
    heading = indicator.findChild(QLabel, "output_heading")
    last = max(buttons, key=lambda button: button.x())
    return heading.x() + heading.width() - (last.x() + last.width())


@pytest.mark.parametrize("show_hotkeys", SHOW_HOTKEYS_CASES)
def test_open_when_switch_buttons_same_width(
    qapp: QApplication, tmp_path: Path, show_hotkeys: bool
) -> None:
    """切り替えのボタンを、名前の最も長いボタンが収まる同じ固定の幅にする（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 名前の長さの違う貼り付けて送信・貼り付けのみ・コピーのみがオンの設定
    settings = _switch_settings(show_hotkeys, ALL_OUTPUT_IDS)
    indicator = TranscribingIndicator(
        make_ui_deps(tmp_path, settings=settings), clock=FakeClock(0.0)
    )

    # 実行: 表示を出し、窓を minimumSizeHint の幅にする
    indicator.open()
    indicator.resize(indicator.minimumSizeHint())
    qapp.processEvents()

    # 検証: 3 つのボタンの固定の幅が全て同じ値で、その値が各ボタンの sizeHint の幅の最大以上
    buttons = _switch_buttons(indicator)
    fixed_widths = _fixed_widths(buttons)
    fixed_minimum, fixed_maximum = next(iter(fixed_widths))
    assert len(buttons) == len(ALL_OUTPUT_IDS)
    assert len(fixed_widths) == 1
    assert fixed_minimum == fixed_maximum
    assert fixed_minimum >= _widest_hint(buttons)


@pytest.mark.parametrize("show_hotkeys", SHOW_HOTKEYS_CASES)
@pytest.mark.parametrize(
    "enabled_ids",
    [
        pytest.param(ALL_OUTPUT_IDS, id="three_outputs_on"),
        pytest.param(TWO_OUTPUT_IDS, id="two_outputs_on"),
    ],
)
@pytest.mark.parametrize(
    "widen_px",
    [
        pytest.param(1, id="widen_1px"),
        pytest.param(2, id="widen_2px"),
        pytest.param(3, id="widen_3px"),
    ],
)
def test_open_when_window_widened(
    qapp: QApplication,
    tmp_path: Path,
    widen_px: int,
    enabled_ids: tuple[str, ...],
    show_hotkeys: bool,
) -> None:
    """窓を広げても切り替えのボタンの幅が全て同じ（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: オンの出力先を enabled_ids にした設定で表示を出す
    settings = _switch_settings(show_hotkeys, enabled_ids)
    indicator = TranscribingIndicator(
        make_ui_deps(tmp_path, settings=settings), clock=FakeClock(0.0)
    )
    indicator.open()

    # 実行: 窓を minimumSizeHint の幅から widen_px 広げる
    _widen_from_minimum(qapp, indicator, widen_px)

    # 検証: ボタンの width() が全て同じ値で、最後のボタンの右に残る空きがボタンの数より小さい px
    buttons = _switch_buttons(indicator)
    free_space = _free_space_right_of_last(indicator, buttons)
    assert len(buttons) == len(enabled_ids)
    assert len({button.width() for button in buttons}) == 1
    assert 0 <= free_space < len(buttons)


@pytest.mark.parametrize("show_hotkeys", SHOW_HOTKEYS_CASES)
def test_open_when_previous_window_wide(
    qapp: QApplication, tmp_path: Path, show_hotkeys: bool
) -> None:
    """前の回の広い窓の幅を引き継がず、切り替えのボタンを名前の最も長いボタンの幅で並べる（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 3 つの出力先がオンの設定で open し、窓を前の回の広い幅にする
    settings = _switch_settings(show_hotkeys, ALL_OUTPUT_IDS)
    indicator = TranscribingIndicator(
        make_ui_deps(tmp_path, settings=settings), clock=FakeClock(0.0)
    )
    indicator.open()
    indicator.resize(PREVIOUS_WINDOW_WIDTH_PX, indicator.height())
    qapp.processEvents()

    # 実行: もう一度 open し、窓を minimumSizeHint の幅にする
    indicator.open()
    indicator.resize(indicator.minimumSizeHint())
    qapp.processEvents()

    # 検証: 3 つのボタンの width() が全て、各ボタンの sizeHint の幅の最大と等しい
    buttons = _switch_buttons(indicator)
    assert len(buttons) == len(ALL_OUTPUT_IDS)
    assert {button.width() for button in buttons} == {_widest_hint(buttons)}


def test_set_progress(qapp: QApplication, tmp_path: Path) -> None:
    """進みと残りを出す（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 時計は表示を出したとき 0 秒、進みを受けたとき 3.0 秒
    clock = FakeClock(0.0)
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=clock)
    indicator.open()
    clock.now = 3.0

    # 実行
    indicator.set_progress(3.1, 5.0)

    # 検証
    progress_bar = indicator.findChild(QProgressBar, "progress_bar")
    time_label = indicator.findChild(QLabel, "time_label")
    assert progress_bar.value() == 62
    assert time_label.text() == "経過 3.0 秒 残り 2 秒 / 5 秒"


def test_set_output(qapp: QApplication, tmp_path: Path) -> None:
    """印と案内を切り替えた先に替える（正常系）。"""
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 貼り付けて送信・貼り付けのみ・コピーのみがオンの設定で、貼り付けて送信で確定した表示を出す
    indicator = TranscribingIndicator(make_ui_deps(tmp_path), clock=FakeClock(0.0))
    indicator.open(output_id="paste_and_send")

    # 実行
    indicator.set_output("copy_only")

    # 検証
    checked = {
        output_id: indicator.findChild(QPushButton, f"switch_button_{output_id}").isChecked()
        for output_id in OUTPUT_TITLES
    }
    paste_hint = indicator.findChild(QLabel, "paste_hint")
    assert checked == {"paste_and_send": False, "paste_only": False, "copy_only": True}
    assert paste_hint.text() == "起こした文字をクリップボードにコピーします"


# === 丸い印と文字の重なり ===

BADGE_ERODE_PX = 1
"""丸い印の画素を探すとき、同じ色の画素を内側へ削る幅（1 px の枠の線を落とし、円の塊だけを残す）。"""

BADGE_RIM_PX = 1
"""丸い印の縁の、なだらかに色が混ざって印の色と一致しない画素の幅。"""


@pytest.fixture
def light_app(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    """明るい組のスタイルシートを当てた QApplication を返し、テストの後にスタイルシートと Qt の明暗の上書きを外す。"""
    from voice_paste.ui.style import apply_theme

    monkeypatch.setattr("voice_paste.ui.style._current_dark", None, raising=False)
    monkeypatch.setattr("voice_paste.ui.style.is_dark_theme", MagicMock(return_value=False))
    apply_theme(qapp, "light")
    yield qapp
    qapp.setStyleSheet("")
    qapp.styleHints().unsetColorScheme()


def _badge_range(button: QPushButton) -> QRect | None:
    """選んだボタンの丸い印の範囲を、ボタンを描いた画像から求める（印が描かれていなければ None）。

    印の色（accent_fg）の画素のうち、周りの画素も同じ色のものだけを残して細い枠の線を落とし、残った画素の外接の四角を削った幅と縁の幅だけ広げる。
    """
    from voice_paste.ui.style import theme_color

    # 準備: ボタンを子の部品ごと画像に描く
    image = QImage(button.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    button.render(image)

    # 印の色の画素を集める
    accent = theme_color("accent_fg").rgb()
    solid = {
        (x, y)
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).rgb() == accent
    }

    # 周りも同じ色の画素だけを残す（円の塊が残り、1 px の線は消える）
    around = range(-BADGE_ERODE_PX, BADGE_ERODE_PX + 1)
    inner = [
        (x, y)
        for x, y in solid
        if all((x + dx, y + dy) in solid for dx in around for dy in around)
    ]
    # 印の色の塊が無い: 印は描かれていない
    if not inner:
        return None

    grow = BADGE_ERODE_PX + BADGE_RIM_PX
    left = min(x for x, _ in inner) - grow
    top = min(y for _, y in inner) - grow
    right = max(x for x, _ in inner) + grow
    bottom = max(y for _, y in inner) + grow
    return QRect(left, top, right - left + 1, bottom - top + 1)


def _name_range(button: QPushButton, label: QLabel) -> QRect:
    """名前のラベルの文字の範囲を、QFontMetrics で求めた文字の幅をラベルの配置でボタンの座標へ移して返す。"""
    metrics = QFontMetrics(label.font())
    area = label.contentsRect()
    text_width = metrics.horizontalAdvance(label.text())
    alignment = label.alignment()

    # 横の配置: 右寄せ・中央・左寄せ
    if alignment & Qt.AlignmentFlag.AlignRight:
        left = area.right() + 1 - text_width
    elif alignment & Qt.AlignmentFlag.AlignHCenter:
        left = area.left() + (area.width() - text_width) // 2
    else:
        left = area.left()

    # 縦の配置: 下寄せ・上寄せ・中央
    if alignment & Qt.AlignmentFlag.AlignBottom:
        top = area.bottom() + 1 - metrics.height()
    elif alignment & Qt.AlignmentFlag.AlignTop:
        top = area.top()
    else:
        top = area.top() + (area.height() - metrics.height()) // 2

    return QRect(label.mapTo(button, QPoint(left, top)), QSize(text_width, metrics.height()))


def _text_ranges(button: QPushButton) -> list[QRect]:
    """ボタンの名前の文字の範囲と、ホットキーのラベルの範囲を、ボタンの座標で並べて返す（ホットキーを出さないボタンは名前の分だけ）。"""
    ranges: list[QRect] = []
    for label in button.findChildren(QLabel):
        # ホットキーのラベル（keycap）はラベルの範囲を、名前のラベルは文字の範囲を取る
        if label.property("role") == "keycap":
            ranges.append(QRect(label.mapTo(button, QPoint(0, 0)), label.size()))
        else:
            ranges.append(_name_range(button, label))
    return ranges


def _ranges_touching(badge: QRect, ranges: list[QRect]) -> list[QRect]:
    """範囲の並びのうち、丸い印の範囲と交わるものを返す。"""
    return [text_range for text_range in ranges if text_range.intersects(badge)]


@pytest.mark.parametrize(
    ("show_hotkeys", "range_count"),
    [
        pytest.param(True, 2, id="hotkeys_on"),
        pytest.param(False, 1, id="hotkeys_off"),
    ],
)
@pytest.mark.parametrize(
    "output_id",
    [
        pytest.param("paste_and_send", id="paste_and_send"),
        pytest.param("paste_only", id="paste_only"),
        pytest.param("copy_only", id="copy_only"),
    ],
)
def test_set_output_badge_clear_of_text(
    light_app: QApplication,
    tmp_path: Path,
    output_id: str,
    show_hotkeys: bool,
    range_count: int,
) -> None:
    """選んだボタンの丸い印が名前とホットキーの文字に重ならない（正常系）。"""
    from voice_paste.main import SETTINGS_MODEL
    from voice_paste.shared.settings import UiSettings
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    # 準備: 貼り付けて送信・貼り付けのみ・コピーのみがオンの設定で、貼り付けて送信で確定した表示を出す
    settings = SETTINGS_MODEL(
        ui=UiSettings(show_hotkeys=True, transcribing_show_hotkeys=show_hotkeys)
    )
    indicator = TranscribingIndicator(
        make_ui_deps(tmp_path, settings=settings), clock=FakeClock(0.0)
    )
    indicator.open(output_id="paste_and_send")

    # 実行
    indicator.set_output(output_id)

    # 検証: 印が描かれ、名前（とホットキー）の範囲が取れ、どれも印の範囲と交わらない
    button = indicator.findChild(QPushButton, f"switch_button_{output_id}")
    badge = _badge_range(button)
    text_ranges = _text_ranges(button)
    assert badge is not None
    assert len(text_ranges) == range_count
    assert _ranges_touching(badge, text_ranges) == []
