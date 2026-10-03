"""画面設計「トレイの通知」を元にした結合テスト。

本物のトレイと UiController をつなぎ、Windows の通知（QSystemTrayIcon.showMessage）は差し替えて、見出しと本文を確かめる。
通知を押したときの振る舞い（messageClicked）は offscreen で確かめる。通知センターから押したときは実機の E2E に残す。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QSystemTrayIcon

from tests.integration.ui.helpers import Ui

NOTIFICATIONS = [
    pytest.param(
        "microphone_unavailable",
        None,
        "録音を始められませんでした",
        "マイクを開けません。マイクがつながっているか、ほかのアプリが使っていないかを確かめてください。",
        id="microphone_unavailable",
    ),
    pytest.param(
        "transcription_failed",
        "録音を読めませんでした",
        "文字起こしに失敗しました",
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
        "API を使えません",
        "ポート 47823 で待ち受けを始められません。ホットキーとトレイからの録音は使えます。",
        id="api_unavailable",
    ),
]
"""知らせの種類・理由・見出し・本文（画面設計の「知らせの種類ごとの文言」の表）。"""


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """QSystemTrayIcon.showMessage を差し替え、出した通知（見出し・本文）を覚える Mock を返す。"""
    show_message = MagicMock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)
    return show_message


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
        ("engine_unavailable", "モデルを読めません", "起動に失敗しました"),
        ("settings_invalid", "api.port: 1024〜65535 の値を入れてください", "起動に失敗しました"),
    ],
)
def test_tray_notification_when_startup_failed(
    make_ui: Callable[..., Ui], shown: MagicMock, event: str, reason: str, title: str
) -> None:
    """文字起こしのエンジンを準備できなかった・設定ファイルを読めなかった起動のときも、通知を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure(event, reason)  # type: ignore[arg-type]

    # 検証
    shown.assert_called_once()
    assert shown.call_args.args[0] == title


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


def test_notification_body_when_engine_unavailable(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """文字起こしのエンジンを準備できない起動の本文は、理由と「設定を直して再起動してください」を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure("engine_unavailable", "モデルを読めません")

    # 検証
    assert shown.call_args.args[1] == (
        "文字起こしのエンジンを準備できません（モデルを読めません）。設定を直して再起動してください。"
    )


def test_notification_body_when_settings_invalid(
    make_ui: Callable[..., Ui], shown: MagicMock
) -> None:
    """設定ファイルを読めない起動の本文は、理由と「設定フォルダの settings.toml を直して再起動してください」を出す。"""
    # 準備
    ui = make_ui()

    # 実行
    ui.tray.show_failure("settings_invalid", "api.port が合わない")

    # 検証
    assert shown.call_args.args[1] == (
        "設定ファイルを読めません（api.port が合わない）。設定フォルダの settings.toml を直して再起動してください。"
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
