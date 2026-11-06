"""画面設計「トレイの通知」を元にした結合テスト。

本物のトレイと UiController をつなぎ、Windows の通知（QSystemTrayIcon.showMessage）は差し替えて、見出しと本文を確かめる。
通知を押したときの振る舞い（messageClicked）は offscreen で確かめる。畳まれる前の通知を押したときは確かめていない。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QSystemTrayIcon

from tests.integration.ui.helpers import Ui
from voice_paste.shared.errors import DeliveryError
from voice_paste.ui.bridge import UiBridge, notify_copied

NOTIFICATIONS = [
    pytest.param(
        "microphone_unavailable",
        None,
        "録音を開始できませんでした",
        "マイクを使用できません。マイクが接続されているか、ほかのアプリが使用していないかを確認してください。",
        id="microphone_unavailable",
    ),
    pytest.param(
        "transcription_failed",
        "録音を読めませんでした",
        "文字起こしできませんでした",
        "録音を読めませんでした。録音は履歴に残っています。",
        id="transcription_failed",
    ),
    pytest.param(
        "delivery_failed",
        "クリップボードに書けませんでした",
        "届けられませんでした",
        "クリップボードに書けませんでした。起こした文字は履歴に残っています。",
        id="delivery_failed",
    ),
    pytest.param(
        "api_unavailable",
        "ポート 47823 で待ち受けを始められません",
        "API を使用できません",
        "ポート 47823 で待ち受けを始められません。ホットキーとトレイからの録音は使えます。",
        id="api_unavailable",
    ),
    pytest.param(
        "delivery_failed",
        "貼り付けのキーを送信できません。起こした文字はクリップボードにあります",
        "届けられませんでした",
        "貼り付けのキーを送信できません。起こした文字はクリップボードにあります。起こした文字は履歴に残っています。",
        id="delivery_failed_when_wayland_key_sender_not_opened",
    ),
]
"""知らせの種類・理由・見出し・本文（画面設計の「知らせの種類ごとの文言」の表）。"""


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """QSystemTrayIcon.showMessage を差し替え、出した通知（見出し・本文）を覚える Mock を返す。"""
    show_message = MagicMock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)
    return show_message


def notify_copy_completed(ui: Ui, text: str) -> None:
    """UiBridge.copied を UiController.on_copied につなぎ（main.py の配線と同じ向き）、notify_copied でコピーの完了を知らせる。"""
    bridge = UiBridge()
    bridge.copied.connect(ui.controller.on_copied)
    notify_copied(text, bridge=bridge)


# === tray_notification ===


@pytest.mark.parametrize(("event", "detail", "title", "body"), NOTIFICATIONS)
def test_tray_notification_visible_when(
    make_ui: Callable[..., Ui], shown: MagicMock, event: str, detail: str | None, title: str, body: str
) -> None:
    """microphone_unavailable・transcription_failed・delivery_failed・api_unavailable を受けたとき、通知を 1 つ出す（表示条件）。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.on_notified(event, detail)

    # 検証
    shown.assert_called_once()


@pytest.mark.parametrize("event", ["state_changed", "busy", "unknown"])
def test_tray_notification_not_visible_when(
    make_ui: Callable[..., Ui], shown: MagicMock, event: str
) -> None:
    """状態の変化・処理中の知らせ・知らない知らせでは、通知を出さない。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.on_notified(event, None)

    # 検証
    shown.assert_not_called()


@pytest.mark.parametrize(
    ("event", "reason", "title"),
    [
        ("engine_unavailable", "モデルを読めません", "起動できませんでした"),
        ("engine_fallback", "切り戻す", "Haas を使用できません"),
        ("settings_invalid", "api.port: 1024〜65535 の値を入れてください", "起動できませんでした"),
        ("paste_unavailable", "Permission denied", "貼り付けを使用できません"),
    ],
)
def test_tray_notification_when_startup_failed(
    make_ui: Callable[..., Ui], shown: MagicMock, event: str, reason: str, title: str
) -> None:
    """文字起こしのエンジンを準備できなかった・設定ファイルを読めなかった・貼り付けのキーを送信する仮想のキーボードを作れなかった起動のときも、通知を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure(event, reason)  # type: ignore[arg-type]

    # 検証
    shown.assert_called_once()
    assert shown.call_args.args[0] == title


def test_tray_notification_when_copy_completed(make_ui: Callable[..., Ui], shown: MagicMock) -> None:
    """notify_copied でコピーの完了を受けたとき、情報のアイコンの通知を 1 つ出す（表示条件）。"""
    # 準備
    ui = make_ui()

    # 実行
    notify_copy_completed(ui, "起こした文字")

    # 検証
    shown.assert_called_once()
    assert shown.call_args.args[2] == QSystemTrayIcon.MessageIcon.Information


@pytest.mark.parametrize("event", ["microphone_unavailable", "delivery_failed"])
def test_tray_notification_icon_when_failed(
    make_ui: Callable[..., Ui], shown: MagicMock, event: str
) -> None:
    """失敗の通知は、今までどおり警告のアイコンで出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.on_notified(event, None)

    # 検証
    assert shown.call_args.args[2] == QSystemTrayIcon.MessageIcon.Warning


# === notification_title・notification_body ===


@pytest.mark.parametrize(("event", "detail", "title", "body"), NOTIFICATIONS)
def test_notification_title_and_body(
    make_ui: Callable[..., Ui], shown: MagicMock, event: str, detail: str | None, title: str, body: str
) -> None:
    """知らせの種類ごとの見出しと、理由を 1 文で出し履歴に残っていること・次にすることを添えた本文を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.controller.on_notified(event, detail)

    # 検証
    args: tuple[Any, ...] = shown.call_args.args
    assert args[0] == title
    assert args[1] == body


def test_notification_title_and_body_when_copy_completed(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """コピーの完了の見出しは「コピーしました」、本文は貼り付けることと、通知を押すとコピーし直せることを固定の文で出す（起こした文字は出さない）。"""
    # 準備
    ui = make_ui()

    # 実行
    notify_copy_completed(ui, "起こした文字")

    # 検証
    args: tuple[Any, ...] = shown.call_args.args
    assert args[0] == "コピーしました"
    assert args[1] == "任意の場所に貼り付けてください。この通知を押すと、もう一度コピーします。"


def test_notification_body_when_engine_fallback(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """Haas から切り戻した起動の本文は、切り戻しの文だけを出す。"""
    # 準備
    ui = make_ui()
    message = "Haas のサーバーへ接続できないため、ローカルの Whisper で起こします。"

    # 実行
    ui.tray.show_failure("engine_fallback", message)

    # 検証
    assert shown.call_args.args[:2] == ("Haas を使用できません", message)


def test_notification_body_when_engine_unavailable(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """文字起こしのエンジンを準備できない起動の本文は、理由と「設定を修正して再起動してください」を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure("engine_unavailable", "モデルを読めません")

    # 検証
    assert shown.call_args.args[1] == (
        "文字起こしのエンジンを準備できませんでした（モデルを読めません）。設定を修正して再起動してください。"
    )


@pytest.mark.parametrize(
    ("paths", "shown_paths"),
    [
        pytest.param(
            (PureWindowsPath("C:/a/settings.yaml"),), "C:\\a\\settings.yaml", id="one_file"
        ),
        pytest.param(
            (PureWindowsPath("C:/a/settings.yaml"), PureWindowsPath("C:/r/settings.local.yaml")),
            "C:\\a\\settings.yaml・C:\\r\\settings.local.yaml",
            id="two_files",
        ),
    ],
)
def test_notification_body_when_settings_invalid(
    make_ui: Callable[..., Ui],
    shown: MagicMock,
    paths: tuple[PureWindowsPath, ...],
    shown_paths: str,
) -> None:
    """設定ファイルを読めない起動の本文は、理由と「{読めなかったファイルのパス} を修正して再起動してください」を出す。読めなかったファイルが複数なら「・」でつなぐ。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure("settings_invalid", "api.port が合わない", paths=paths)

    # 検証
    assert shown.call_args.args[1] == (
        f"設定ファイルを読み込めませんでした（api.port が合わない）。{shown_paths} を修正して再起動してください。"
    )


def test_notification_body_when_paste_unavailable(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """貼り付けのキーを送信できない起動の本文は、理由と /dev/uinput の権限の設定の手順と「コピーのみ」を使えることを出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure("paste_unavailable", "Permission denied")

    # 検証
    assert shown.call_args.args[1] == (
        "貼り付けのキーを送信できません（Permission denied）。/dev/uinput の権限を設定して PC を再起動してください（使い方「起動と設定」）。「コピーのみ」は使えます。"
    )


# === open_log_folder ===


def test_open_log_folder_when_clicked(
    make_ui: Callable[..., Ui], shown: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """通知を押すと（messageClicked）、ログのフォルダをエクスプローラーで開く。"""
    # 準備
    urls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", MagicMock(side_effect=urls.append))
    ui = make_ui()
    ui.controller.on_notified("delivery_failed", "クリップボードに書けませんでした")

    # 実行
    ui.tray._icon.messageClicked.emit()

    # 検証
    assert [Path(url.toLocalFile()) for url in urls] == [ui.deps.log_dir]


def test_open_log_folder_when_not_clicked(
    make_ui: Callable[..., Ui], shown: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """通知を出しただけでは、フォルダを開かない（閉じると待機中のトレイに戻る）。"""
    # 準備
    open_url = MagicMock()
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    ui = make_ui()

    # 実行
    ui.controller.on_notified("delivery_failed", "クリップボードに書けませんでした")
    ui.notify_state(None)

    # 検証
    open_url.assert_not_called()
    assert ui.tray._icon.toolTip() == "voice-paste: 待機中"


def test_open_log_folder_when_clicked_after_failure_following_copy_completed(
    make_ui: Callable[..., Ui], shown: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """コピーの完了の通知の後に失敗の通知が出ていれば、通知を押してもコピーし直さず、ログのフォルダを開く。"""
    # 準備
    urls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", MagicMock(side_effect=urls.append))
    ui = make_ui()
    notify_copy_completed(ui, "起こした文字")
    ui.controller.on_notified("delivery_failed", "クリップボードに書けませんでした")

    # 実行
    ui.tray._icon.messageClicked.emit()

    # 検証
    assert [Path(url.toLocalFile()) for url in urls] == [ui.deps.log_dir]
    ui.deps.copy.assert_not_called()


def test_open_log_folder_when_clicked_copy_completed(
    make_ui: Callable[..., Ui], shown: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """コピーの完了の通知を押しても、ログのフォルダは開かない。"""
    # 準備
    open_url = MagicMock()
    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    ui = make_ui()
    notify_copy_completed(ui, "起こした文字")

    # 実行
    ui.tray._icon.messageClicked.emit()

    # 検証
    open_url.assert_not_called()


# === recopy ===


def test_recopy_when_clicked(make_ui: Callable[..., Ui], shown: MagicMock) -> None:
    """コピーの完了の通知を押すと、その通知のときに起こした文字をクリップボードへもう一度書く。"""
    # 準備
    ui = make_ui()
    notify_copy_completed(ui, "起こした文字")

    # 実行
    ui.tray._icon.messageClicked.emit()

    # 検証
    ui.deps.copy.assert_called_once_with("起こした文字")


def test_recopy_when_clicked_after_next_copy_completed(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """コピーの完了の通知が続いたときは、最後に出した通知のときに起こした文字をもう一度コピーする。"""
    # 準備
    ui = make_ui()
    notify_copy_completed(ui, "1 回目の文字")
    notify_copy_completed(ui, "2 回目の文字")

    # 実行
    ui.tray._icon.messageClicked.emit()

    # 検証
    ui.deps.copy.assert_called_once_with("2 回目の文字")


def test_recopy_when_not_clicked(make_ui: Callable[..., Ui], shown: MagicMock) -> None:
    """通知を出しただけでは、コピーし直さない。"""
    # 準備
    ui = make_ui()

    # 実行
    notify_copy_completed(ui, "起こした文字")
    ui.notify_state(None)

    # 検証
    ui.deps.copy.assert_not_called()


def test_recopy_when_copy_failed(make_ui: Callable[..., Ui], shown: MagicMock) -> None:
    """コピーし直せなければ、delivery_failed の失敗の通知（警告のアイコン）を出す。"""
    # 準備
    ui = make_ui(copy=MagicMock(side_effect=DeliveryError("クリップボードに書けませんでした")))
    notify_copy_completed(ui, "起こした文字")

    # 実行
    ui.tray._icon.messageClicked.emit()

    # 検証
    assert shown.call_count == 2
    args: tuple[Any, ...] = shown.call_args.args
    assert args[0] == "届けられませんでした"
    assert args[1] == "クリップボードに書けませんでした。起こした文字は履歴に残っています。"
    assert args[2] == QSystemTrayIcon.MessageIcon.Warning
