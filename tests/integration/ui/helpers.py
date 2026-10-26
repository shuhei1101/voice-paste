"""画面の結合テスト用の補助。

画面は offscreen の QApplication（tests/conftest.py の qapp）で開き、UiDeps は差し替えた関数（Mock）で受ける。
単体テストと同じ UiDeps・Session の組み立てを使い回す。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QWidget,
)

from tests.unit.voice_paste.ui.helpers import FakeClock, make_session, make_ui_deps

if TYPE_CHECKING:
    from voice_paste.shared.settings import Preset, Settings
    from voice_paste.ui.controller import UiController, UiDeps
    from voice_paste.ui.tray import Tray
    from voice_paste.ui.windows.recording_window import RecordingWindow
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

__all__ = ["FakeClock", "make_session", "make_ui_deps"]

WidgetT = TypeVar("WidgetT", bound=QWidget)


def top_level_windows() -> set[QWidget]:
    """今ある、親を持たない窓（トップレベルの部品）の集合を返す。"""
    return set(QApplication.topLevelWidgets())


def flush_deletions() -> None:
    """deleteLater した部品の破棄を流し終える。"""
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def dispose_windows_since(before: set[QWidget]) -> None:
    """before に無かったトップレベルの窓を、隠した上で破棄し、破棄を流し終える。"""
    for window in top_level_windows() - before:
        if isinstance(window, QDialog):
            # ダイアログは finished を知らせて閉じる（持ち主が出ているダイアログを手放せるように）
            window.reject()
        else:
            # 閉じる確認を出させないよう、close ではなく隠す
            window.hide()
        window.deleteLater()
    flush_deletions()


def find(root: QWidget, cls: type[WidgetT], name: str) -> WidgetT:
    """画面の項目 ID（objectName）の部品を引く。無ければ失敗させる。"""
    found = root.findChild(cls, name)
    assert found is not None, f"{name} の部品が無い"
    return found


def button_texts(button: QPushButton) -> list[str]:
    """ボタンの中に並んだ文字（名前・ホットキー）を、並びの順に返す。"""
    return [label.text() for label in button.findChildren(QLabel)]


def grab_head_row(window: RecordingWindow) -> None:
    """録音の画面の見出しの行（head_row）の中ほどを押して放す（窓の移動は startSystemMove に任せる）。"""
    row = find(window, QWidget, "head_row")
    QTest.mousePress(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
    QTest.mouseRelease(row, Qt.MouseButton.LeftButton, pos=row.rect().center())


FACE_OFFSET_PX = 4
"""窓の左端から、縁と角丸の内側（面だけが描かれる位置）までの距離。"""


def edge_and_face_colors(widget: QWidget) -> tuple[QColor, QColor]:
    """窓を描いた画像の、左端の縦の中ほどの画素の色（窓の外側の縁）と、そこから内側へ進んだ画素の色（窓の面）を返す。"""
    image = widget.grab().toImage()
    middle = image.height() // 2
    return image.pixelColor(0, middle), image.pixelColor(FACE_OFFSET_PX, middle)


BADGE_ERODE_PX = 1
"""丸いマーカーの画素を探すとき、同じ色の画素を内側へ削る幅（1 px の枠の線を落とし、円の塊だけを残す）。"""

BADGE_RIM_PX = 1
"""丸いマーカーの縁の、なだらかに色が混ざってマーカーの色と一致しない画素の幅。"""


def face_range(button: QPushButton) -> QRect:
    """出力先の切り替えのボタンの、右と上の余白（マーカーがはみ出す分）を除いた枠の範囲を、ボタンの座標で返す。"""
    from voice_paste.ui.style import load_tokens

    overhang: int = load_tokens()["shape"]["badge_overhang"]
    return button.rect().adjusted(0, overhang, -overhang, 0)


def badge_range(button: QPushButton) -> QRect | None:
    """選んだボタンの丸いマーカーの範囲を、ボタンを描いた画像から求める（マーカーが描かれていなければ None）。

    マーカーの色（accent_fg）の画素のうち、周りの画素も同じ色のものだけを残して細い枠の線を落とし、残った画素の外接の四角を削った幅と縁の幅だけ広げる。
    """
    from voice_paste.ui.style import theme_color

    # ボタンを子の部品ごと画像に描く
    image = QImage(button.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    button.render(image)

    # マーカーの色の画素を集める
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
    # マーカーの色の塊が無い: マーカーは描かれていない
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


def text_ranges(button: QPushButton) -> list[QRect]:
    """ボタンの名前の文字の範囲と、ホットキーのラベルの範囲を、ボタンの座標で並べて返す（ホットキーを出さないボタンは名前の分だけ）。"""
    ranges: list[QRect] = []
    for label in button.findChildren(QLabel):
        # ホットキーのラベル（keycap）はラベルの範囲を、名前のラベルは文字の範囲を取る
        if label.property("role") == "keycap":
            ranges.append(QRect(label.mapTo(button, QPoint(0, 0)), label.size()))
        else:
            ranges.append(_name_range(button, label))
    return ranges


def content_range(button: QPushButton) -> QRect:
    """ボタンの中の名前とホットキーのラベルを全て含む範囲を、ボタンの座標で返す。"""
    result = QRect()
    for label in button.findChildren(QLabel):
        result = result.united(QRect(label.mapTo(button, QPoint(0, 0)), label.size()))
    return result


@dataclass
class Ui:
    """本物のトレイ・録音の画面・文字起こし中の表示を UiController へつないだ一式と、渡した UiDeps・録音の画面の時計。"""

    controller: UiController
    tray: Tray
    recording_window: RecordingWindow
    indicator: TranscribingIndicator
    deps: UiDeps
    clock: FakeClock

    def notify_state(
        self,
        entry: str | None,
        state: str | None = None,
        *,
        output_id: str | None = None,
        output_preset: Preset | None = None,
    ) -> None:
        """今のセッションを入口・状態・確定で選んだ出力先かプリセットで差し替え、state_changed を受けさせる（None は待機中）。"""
        session = (
            None
            if entry is None
            else make_session(
                entry, state or "recording", output_id=output_id, output_preset=output_preset
            )
        )
        self.deps.current_session.return_value = session
        self.controller.on_notified("state_changed", None)

    def notify_output_changed(self, output_id: str) -> None:
        """届ける出力先を差し替えたことを知らせる（output_changed）。"""
        self.controller.on_notified("output_changed", output_id)

    def advance_clock(self, seconds: float) -> None:
        """録音の画面の時計を seconds 秒進め、描き直し（WAVE_INTERVAL_MS）を跨ぐ分だけ待つ。"""
        from voice_paste.ui.windows.recording_window import WAVE_INTERVAL_MS

        self.clock.now += seconds
        QTest.qWait(WAVE_INTERVAL_MS * 2)

    def close(self) -> None:
        """出ている窓とトレイを隠し、破棄を予約する（破棄を流し終えるのは dispose_windows_since）。"""
        self.recording_window.close_window()
        self.indicator.close_window()
        self.tray.hide()
        self.recording_window.deleteLater()
        self.indicator.deleteLater()
        self.tray.deleteLater()


def build_ui(tmp_path: Path, settings: Settings | None = None, **deps_overrides: object) -> Ui:
    """本物のトレイ・窓を UiController へつないで返す（UiDeps の関数は Mock）。"""
    from voice_paste.ui.controller import UiController
    from voice_paste.ui.tray import Tray
    from voice_paste.ui.windows.recording_window import RecordingWindow
    from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

    deps = make_ui_deps(tmp_path, settings=settings, **deps_overrides)
    tray = Tray(settings_dir=deps.settings_dir, log_dir=deps.log_dir)
    clock = FakeClock()
    recording_window = RecordingWindow(deps, clock=clock)
    indicator = TranscribingIndicator(deps)
    controller = UiController(
        deps, tray=tray, recording_window=recording_window, indicator=indicator
    )
    return Ui(
        controller=controller,
        tray=tray,
        recording_window=recording_window,
        indicator=indicator,
        deps=deps,
        clock=clock,
    )


class ModalDriver:
    """exec で止まるモーダルのダイアログに、ボタンの項目 ID を押させる。

    answer で予約してから、ダイアログを出す操作を行い、verify で押せたかを確かめる。
    """

    def __init__(self) -> None:
        self.answered = False
        self.error: BaseException | None = None
        self.box: QMessageBox | None = None

    def answer(
        self, button_name: str, inspect: Callable[[QMessageBox], None] | None = None
    ) -> None:
        """次に出るモーダルで inspect（あれば）を呼び、button_name のボタンを押す。"""

        def _click() -> None:
            """モーダルのダイアログを引いて、見て、ボタンを押す。"""
            box = QApplication.activeModalWidget()
            try:
                assert isinstance(box, QMessageBox), "モーダルのダイアログが出ていない"
                self.box = box
                if inspect is not None:
                    inspect(box)
                find(box, QPushButton, button_name).click()
                self.answered = True
            except BaseException as error:  # noqa: BLE001 タイマーの中の失敗を verify で出し直す
                self.error = error
                if isinstance(box, QMessageBox):
                    box.reject()

        QTimer.singleShot(0, _click)

    def verify(self) -> None:
        """ダイアログの確認とボタンの押下が済んでいることを確かめる（失敗はここで出し直す）。"""
        if self.error is not None:
            raise self.error
        assert self.answered, "モーダルのダイアログが出なかった"


@contextmanager
def no_modal() -> Iterator[None]:
    """この中でモーダルのダイアログが出たら、押せないままブロックしないよう閉じて失敗させる。"""
    seen: list[QMessageBox] = []

    def _watch() -> None:
        """モーダルが出ていたら、閉じて控える。"""
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            seen.append(box)
            box.reject()

    timer = QTimer()
    timer.timeout.connect(_watch)
    timer.start(20)
    try:
        yield
    finally:
        timer.stop()
    assert not seen, "出てはいけないダイアログが出た"


COLOR_TOLERANCE = 6
"""同じ色とみなす、赤・緑・青のそれぞれの差の上限（縁のなだらかな混ざりを許す）。"""

HALF_ALPHA = 128
"""縁の画素のうち、色を比べる不透明度の下限（これ未満は背景の透明が混ざりすぎる）。"""

OPAQUE_ALPHA = 255
"""完全に塗られた画素の不透明度。"""


def color_distance(color: QColor, hex_color: str) -> int:
    """2 色の、赤・緑・青のそれぞれの差の最大を返す。"""
    other = QColor(hex_color)
    return max(
        abs(color.red() - other.red()),
        abs(color.green() - other.green()),
        abs(color.blue() - other.blue()),
    )


def pixel_colors(image: QImage) -> list[QColor]:
    """画像の全ての画素の色を返す。"""
    return [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]


def count_near(image: QImage, hex_color: str) -> int:
    """画像のうち、半分以上が塗られた画素で、色が hex_color に近いものの数を返す。"""
    return sum(
        1
        for color in pixel_colors(image)
        if color.alpha() >= HALF_ALPHA and color_distance(color, hex_color) <= COLOR_TOLERANCE
    )


def count_closer(image: QImage, hex_color: str, other_hex_color: str) -> int:
    """画像のうち、完全に塗られた画素で、other_hex_color より hex_color に近いものの数を返す。"""
    return sum(
        1
        for color in pixel_colors(image)
        if color.alpha() == OPAQUE_ALPHA
        and color_distance(color, hex_color) < color_distance(color, other_hex_color)
    )


def crop_logical(image: QImage, rect: QRect) -> QImage:
    """論理ピクセルの範囲を、画像の拡大率に合わせて切り出す。"""
    scale = image.devicePixelRatio()
    return image.copy(
        QRect(
            round(rect.x() * scale),
            round(rect.y() * scale),
            round(rect.width() * scale),
            round(rect.height() * scale),
        )
    )


def indicator_image(button: QAbstractButton) -> QImage:
    """チェックボックス・ラジオボタンを描いた画像から、マーカー（箱・丸）の範囲だけを切り出す。"""
    element = (
        QStyle.SubElement.SE_CheckBoxIndicator
        if isinstance(button, QCheckBox)
        else QStyle.SubElement.SE_RadioButtonIndicator
    )
    option = QStyleOptionButton()
    option.initFrom(button)
    rect = button.style().subElementRect(element, option, button)
    return crop_logical(button.grab().toImage(), rect)


def srgb_luminance(hex_color: str) -> float:
    """色の相対輝度（WCAG 2.1）を返す。"""
    color = QColor(hex_color)
    channels = [color.redF(), color.greenF(), color.blueF()]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(hex_color: str, other_hex_color: str) -> float:
    """2 色のコントラスト比（WCAG 2.1。1〜21）を返す。"""
    lighter, darker = sorted((srgb_luminance(hex_color), srgb_luminance(other_hex_color)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
