"""画面設計「トレイ」を元にした結合テスト。

本物のトレイを offscreen で作り、メニューの項目は項目 ID（objectName）で引く。
フォルダを開く操作は QDesktopServices.openUrl を差し替えて確かめる。
状態ごとのアイコンとヒントは、本物の UiController の state_changed でも確かめる。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import QSystemTrayIcon

from tests.integration.ui.helpers import Ui, edge_and_face_colors

if TYPE_CHECKING:
    from voice_paste.ui.tray import Tray, TrayState

MENU_ORDER = (
    "menu_start",
    "menu_show_window",
    "",
    "menu_settings",
    "menu_open_settings_folder",
    "menu_open_log_folder",
    "",
    "menu_restart",
    "menu_quit",
)
"""メニューの並び（空は区切り）。"""


def _action(tray: Tray, name: str) -> QAction:
    """トレイのメニューから、項目 ID の項目を引く。"""
    action = tray._icon.contextMenu().findChild(QAction, name)
    assert action is not None, f"{name} の項目が無い"
    return action


def _label(action: QAction) -> str:
    """メニューの項目の文言（右に出すホットキーは除く）を返す。"""
    return action.text().split("\t")[0]


@pytest.fixture
def opened_urls(monkeypatch: pytest.MonkeyPatch) -> list[QUrl]:
    """QDesktopServices.openUrl を差し替え、開こうとした URL を並べたリストを返す。"""
    urls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", MagicMock(side_effect=urls.append))
    return urls


# === tray_icon・tray_tooltip ===


@pytest.mark.parametrize(
    ("state", "name"),
    [
        ("STARTING", "準備中"),
        ("IDLE", "待機中"),
        ("RECORDING", "録音中"),
        ("TRANSCRIBING", "文字起こし中"),
        ("FAILED", "失敗"),
    ],
)
def test_tray_icon_and_tooltip(make_ui: Callable[..., Ui], state: str, name: str) -> None:
    """状態ごとに同梱した画像を出し分け、ヒントに「voice-paste: {状態}」を出す。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()

    # 実行
    ui.tray.set_state(TrayState[state], busy=False)

    # 検証
    assert not ui.tray._icon.icon().isNull()
    assert ui.tray._icon.toolTip() == f"voice-paste: {name}"


def test_tray_icon_when_session_changes(make_ui: Callable[..., Ui]) -> None:
    """状態の変化の知らせで、待機中・録音中・文字起こし中のアイコンとヒントに替わる。"""
    # 準備
    ui = make_ui()
    tooltips = []

    # 実行
    for entry, state in ((None, None), ("hotkey", "recording"), ("hotkey", "transcribing"), (None, None)):
        ui.notify_state(entry, state)
        tooltips.append(ui.tray._icon.toolTip())

    # 検証
    assert tooltips == [
        "voice-paste: 待機中",
        "voice-paste: 録音中",
        "voice-paste: 文字起こし中",
        "voice-paste: 待機中",
    ]


@pytest.mark.parametrize(
    ("state", "tooltip"),
    [("recording", "録音中"), ("transcribing", "文字起こし中")],
)
def test_tray_icon_when_api_session(make_ui: Callable[..., Ui], state: str, tooltip: str) -> None:
    """API から始めた録音の間も、トレイのアイコンが録音中か文字起こし中を示す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.notify_state("api", state)

    # 検証
    assert ui.tray._icon.toolTip() == f"voice-paste: {tooltip}"


def test_tray_icon_when_failed(make_ui: Callable[..., Ui]) -> None:
    """文字起こしのエンジンを準備できなかった起動では、次の起動まで失敗のまま続く。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()
    ui.tray.set_failed()

    # 実行
    ui.tray.set_state(TrayState.IDLE, busy=False)

    # 検証
    assert ui.tray._icon.toolTip() == "voice-paste: 失敗"


def test_tray_icon_left_click(make_ui: Callable[..., Ui]) -> None:
    """左クリック（既定の操作）は「録音を開始」と同じ。押せないときは何もしない。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()
    ui.tray.set_state(TrayState.IDLE, busy=False)
    started = MagicMock()
    ui.tray.start_requested.connect(started)

    # 実行
    ui.tray._icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    ui.tray.set_state(TrayState.RECORDING, busy=True)
    ui.tray._icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    # 検証
    started.assert_called_once()


def test_tray_icon_left_click_when_window_hidden(make_ui: Callable[..., Ui]) -> None:
    """録音の画面を隠している間の左クリックは、「録音の画面を表示」と同じ（録音は始めない）。"""
    # 準備
    ui = make_ui()
    _hide_recording(ui)

    # 実行
    ui.tray._icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    # 検証
    assert ui.recording_window.isVisible()
    ui.deps.start.assert_not_called()


@pytest.mark.parametrize(
    ("entry", "state", "hide_window"),
    [
        pytest.param("hotkey", "recording", False, id="window_shown"),
        pytest.param("hotkey", "recording", True, id="hide_window_setting"),
        pytest.param("api", "recording", False, id="api_recording"),
        pytest.param("hotkey", "transcribing", False, id="transcribing"),
    ],
)
def test_tray_icon_left_click_when_not_hidden(
    make_ui: Callable[..., Ui], entry: str, state: str, hide_window: bool
) -> None:
    """録音から届けるまでの間で、録音の画面を隠していないときの左クリックは何もしない。"""
    from voice_paste.shared.settings import RecordingSettings, Settings

    # 準備
    ui = make_ui(Settings(recording=RecordingSettings(hide_window=hide_window)))
    ui.notify_state(entry, state)
    visible = ui.recording_window.isVisible()
    show_requested = MagicMock()
    ui.tray.show_window_requested.connect(show_requested)

    # 実行
    ui.tray._icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    # 検証
    show_requested.assert_not_called()
    ui.deps.start.assert_not_called()
    assert ui.recording_window.isVisible() is visible


# === menu ===


def test_menu_order(make_ui: Callable[..., Ui]) -> None:
    """メニューは、録音を開始・録音の画面を表示・区切り・設定…・設定フォルダを開く・ログフォルダを開く・区切り・再起動・終了の順に並ぶ。"""
    # 実行
    ui = make_ui()

    # 検証
    names = [action.objectName() for action in ui.tray._icon.contextMenu().actions()]
    assert names == list(MENU_ORDER)


# === menu_start ===


def test_menu_start_label_when_idle(make_ui: Callable[..., Ui]) -> None:
    """待機中は「録音を開始」の右に録音開始のホットキーを出し、押せて、太字で出す。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()

    # 実行
    ui.tray.set_start_hotkey("<ctrl>+<alt>+d")
    ui.tray.set_state(TrayState.IDLE, busy=False)

    # 検証
    action = _action(ui.tray, "menu_start")
    assert action.text() == "録音を開始\tCtrl+Alt+D"
    assert action.isEnabled()
    assert action.font().bold()


def test_menu_start_enabled_when_busy(make_ui: Callable[..., Ui]) -> None:
    """録音から届けるまでの間（API から始めた録音の間を含む）は「録音を開始（処理中）」にして押せず、太字を外す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.notify_state("api", "recording")

    # 検証
    action = _action(ui.tray, "menu_start")
    assert _label(action) == "録音を開始（処理中）"
    assert not action.isEnabled()
    assert not action.font().bold()


def test_menu_start_enabled_when_starting(make_ui: Callable[..., Ui]) -> None:
    """準備中は押せない。"""
    # 実行
    ui = make_ui()

    # 検証
    assert not _action(ui.tray, "menu_start").isEnabled()


def test_menu_start_label_when_failed(make_ui: Callable[..., Ui]) -> None:
    """文字起こしのエンジンを準備できなかった起動では「録音を開始（準備に失敗）」にして押せない。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.set_failed()

    # 検証
    action = _action(ui.tray, "menu_start")
    assert _label(action) == "録音を開始（準備に失敗）"
    assert not action.isEnabled()


def test_menu_start_action(make_ui: Callable[..., Ui]) -> None:
    """「録音を開始」を選ぶと、録音の開始（UiDeps.start）を呼ぶ。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()
    ui.tray.set_state(TrayState.IDLE, busy=False)

    # 実行
    _action(ui.tray, "menu_start").trigger()

    # 検証
    ui.deps.start.assert_called_once()


# === menu_show_window ===


def _hide_recording(ui: Ui) -> None:
    """ホットキーの録音の画面を出し、その回だけ隠す。"""
    ui.notify_state("hotkey", "recording")
    ui.controller.hide_recording()


def test_menu_show_window_when_hidden(make_ui: Callable[..., Ui]) -> None:
    """隠している間は「録音の画面を表示」を押せ、既定の項目として太字で出す（「録音を開始」は太字でない）。"""
    # 準備
    ui = make_ui()

    # 実行
    _hide_recording(ui)

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示"
    assert action.isEnabled()
    assert action.font().bold()
    assert not _action(ui.tray, "menu_start").font().bold()


def test_menu_show_window_when_shown(make_ui: Callable[..., Ui]) -> None:
    """録音の画面が出ている間は「録音の画面を表示（表示中）」にして押せず、太字を外す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.notify_state("hotkey", "recording")

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示（表示中）"
    assert not action.isEnabled()
    assert not action.font().bold()


def test_menu_show_window_when_hide_window_setting(make_ui: Callable[..., Ui]) -> None:
    """画面を出さない設定の録音の間は「録音の画面を表示（画面を表示しない録音）」にして押せない。"""
    from voice_paste.shared.settings import RecordingSettings, Settings

    # 準備
    ui = make_ui(Settings(recording=RecordingSettings(hide_window=True)))

    # 実行
    ui.notify_state("hotkey", "recording")

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示（画面を表示しない録音）"
    assert not action.isEnabled()


@pytest.mark.parametrize("state", ["recording", "paused"])
def test_menu_show_window_when_api_session(make_ui: Callable[..., Ui], state: str) -> None:
    """API から始めた録音の間は「録音の画面を表示（画面を表示しない録音）」にして押せない。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.notify_state("api", state)

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示（画面を表示しない録音）"
    assert not action.isEnabled()


@pytest.mark.parametrize(
    ("entry", "state"),
    [
        pytest.param(None, None, id="idle"),
        pytest.param("hotkey", "transcribing", id="hotkey_transcribing"),
        pytest.param("tray", "delivering", id="tray_delivering"),
        pytest.param("api", "transcribing", id="api_transcribing"),
    ],
)
def test_menu_show_window_when_not_recording(
    make_ui: Callable[..., Ui], entry: str | None, state: str | None
) -> None:
    """待機中・文字起こし中は「録音の画面を表示（録音していません）」にして押せない。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "recording")

    # 実行
    ui.notify_state(entry, state)

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示（録音していません）"
    assert not action.isEnabled()


def test_menu_show_window_when_failed(make_ui: Callable[..., Ui]) -> None:
    """文字起こしのエンジンを準備できなかった起動では「録音の画面を表示（録音していません）」にして押せない。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()

    # 実行
    ui.tray.set_failed()
    ui.tray.set_state(TrayState.IDLE, busy=False)

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示（録音していません）"
    assert not action.isEnabled()


def test_menu_show_window_when_next_recording(make_ui: Callable[..., Ui]) -> None:
    """隠すのはその回だけで、次の録音では「録音の画面を表示（表示中）」に戻る。"""
    # 準備
    ui = make_ui()
    _hide_recording(ui)
    ui.notify_state(None)

    # 実行
    ui.notify_state("hotkey", "recording")

    # 検証
    assert _action(ui.tray, "menu_show_window").text() == "録音の画面を表示（表示中）"


def test_menu_show_window_when_paused_while_hidden(make_ui: Callable[..., Ui]) -> None:
    """隠している間に一時停止しても、押せるまま残る。"""
    # 準備
    ui = make_ui()
    _hide_recording(ui)

    # 実行
    ui.notify_state("hotkey", "paused")

    # 検証
    action = _action(ui.tray, "menu_show_window")
    assert action.text() == "録音の画面を表示"
    assert action.isEnabled()


def test_menu_show_window_action(make_ui: Callable[..., Ui]) -> None:
    """「録音の画面を表示」を選ぶと、隠した録音の画面を戻し、項目は「（表示中）」に替わる。"""
    # 準備
    ui = make_ui()
    _hide_recording(ui)

    # 実行
    _action(ui.tray, "menu_show_window").trigger()

    # 検証
    assert ui.recording_window.isVisible()
    assert _action(ui.tray, "menu_show_window").text() == "録音の画面を表示（表示中）"
    ui.deps.start.assert_not_called()


# === menu_settings ===


def test_menu_settings_enabled_when_idle(make_ui: Callable[..., Ui]) -> None:
    """設定…は、待機中のほか、準備に失敗した起動でも押せる（設定を修正して再起動できるよう）。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()
    ui.tray.set_state(TrayState.IDLE, busy=False)
    idle_enabled = _action(ui.tray, "menu_settings").isEnabled()

    # 実行
    ui.tray.set_failed()

    # 検証
    action = _action(ui.tray, "menu_settings")
    assert idle_enabled
    assert action.isEnabled()
    assert _label(action) == "設定…"


def test_menu_settings_when_busy(make_ui: Callable[..., Ui]) -> None:
    """録音から届けるまでの間（API から始めた録音の間を含む）は「設定…（処理中）」にして押せない。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.notify_state("hotkey", "transcribing")

    # 検証
    action = _action(ui.tray, "menu_settings")
    assert _label(action) == "設定…（処理中）"
    assert not action.isEnabled()


# === menu_open_settings_folder・menu_open_log_folder ===


def test_menu_open_settings_folder_action(
    make_ui: Callable[..., Ui], opened_urls: list[QUrl]
) -> None:
    """「設定フォルダを開く」は settings.toml のあるフォルダをエクスプローラーで開く。"""
    # 準備
    ui = make_ui()

    # 実行
    _action(ui.tray, "menu_open_settings_folder").trigger()

    # 検証
    assert [Path(url.toLocalFile()) for url in opened_urls] == [ui.deps.settings_dir]


def test_menu_open_log_folder_action(make_ui: Callable[..., Ui], opened_urls: list[QUrl]) -> None:
    """「ログフォルダを開く」はログのフォルダをエクスプローラーで開く。"""
    # 準備
    ui = make_ui()

    # 実行
    _action(ui.tray, "menu_open_log_folder").trigger()

    # 検証
    assert [Path(url.toLocalFile()) for url in opened_urls] == [ui.deps.log_dir]


def test_menu_folders_when_always(make_ui: Callable[..., Ui]) -> None:
    """設定フォルダ・ログフォルダ・再起動・終了は、どの状態でも出して押せる。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.notify_state("api", "recording")

    # 検証
    for name in ("menu_open_settings_folder", "menu_open_log_folder", "menu_restart", "menu_quit"):
        assert _action(ui.tray, name).isEnabled()


# === menu_restart・menu_quit ===


def test_menu_restart_action_when_idle(make_ui: Callable[..., Ui]) -> None:
    """待機中に「再起動」を選ぶと、すぐ再起動する。"""
    # 準備
    ui = make_ui()
    ui.notify_state(None)

    # 実行
    _action(ui.tray, "menu_restart").trigger()

    # 検証
    ui.deps.request_restart.assert_called_once()


def test_menu_quit_action_when_idle(make_ui: Callable[..., Ui]) -> None:
    """待機中に「終了」を選ぶと、すぐ終了する。"""
    # 準備
    ui = make_ui()
    ui.notify_state(None)

    # 実行
    _action(ui.tray, "menu_quit").trigger()

    # 検証
    ui.deps.request_quit.assert_called_once()


@pytest.mark.parametrize(
    ("menu", "requested"),
    [("menu_restart", "request_restart"), ("menu_quit", "request_quit")],
)
def test_menu_exit_when_busy(make_ui: Callable[..., Ui], menu: str, requested: str) -> None:
    """処理中に「再起動」「終了」を選ぶと、アイコンはその時点で非表示にし、その回を届け終えてから行う。"""
    # 準備
    ui = make_ui()
    ui.notify_state("hotkey", "transcribing")
    hidden = MagicMock()
    ui.tray._icon.hide = hidden

    # 実行
    _action(ui.tray, menu).trigger()
    called_while_busy = getattr(ui.deps, requested).call_count
    ui.notify_state(None)

    # 検証
    hidden.assert_called_once()
    assert called_while_busy == 0
    getattr(ui.deps, requested).assert_called_once()


def test_menu_settings_action(make_ui: Callable[..., Ui], tmp_path: Path) -> None:
    """「設定…」を選ぶと設定画面を開く。"""
    from voice_paste.ui.tray import TrayState

    # 準備
    ui = make_ui()
    ui.tray.set_state(TrayState.IDLE, busy=False)

    # 実行
    _action(ui.tray, "menu_settings").trigger()

    # 検証
    assert ui.controller._settings_window is not None
    ui.controller._settings_window.try_close()


# === メニューの見た目 ===


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_menu_colors_when_theme(
    make_ui: Callable[..., Ui], apply_theme_to_app: Callable[[str], None], theme: str
) -> None:
    """メニューの面は color.*.surface、外側の縁は color.*.frame の色で描く（* は ui.theme で決まる明暗）。"""
    from voice_paste.ui.style import load_tokens

    # 準備
    apply_theme_to_app(theme)
    ui = make_ui()
    menu = ui.tray._icon.contextMenu()
    menu.ensurePolished()
    menu.resize(menu.sizeHint())

    # 実行
    edge, face = edge_and_face_colors(menu)

    # 検証
    colors = load_tokens()["color"][theme]
    assert edge == QColor(colors["frame"])
    assert face == QColor(colors["surface"])
