"""integrations/keyboard/active_window_wayland.py（read_focused_wm_class）の単体テスト。

subprocess.run は Mock に差し替え、実物の gdbus と GNOME Shell の拡張は呼ばない。
"""

from __future__ import annotations

import logging
import subprocess
from unittest.mock import MagicMock

import pytest

FOCUSED_WINDOW_COMMAND = (
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.Shell",
    "--object-path",
    "/org/gnome/shell/extensions/FocusedWindow",
    "--method",
    "org.gnome.shell.extensions.FocusedWindow.Get",
)
"""拡張 Focused Window D-Bus の Get を呼ぶ gdbus の引数。"""

FOCUSED_WINDOW_TIMEOUT_SEC = 1.0
"""gdbus の応答を待つ秒数。"""

TERMINAL_OUTPUT = (
    "('{\"wm_class\":\"Gnome-terminal\",\"wm_class_instance\":\"gnome-terminal-server\","
    "\"title\":\"端末\"}',)\n"
)
"""GNOME Terminal にフォーカスがあるときの gdbus の標準出力。"""


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """subprocess.run を差し替えた Mock を返す。既定は GNOME Terminal にフォーカスがあるときの出力を返す。"""
    from voice_paste.integrations.keyboard import active_window_wayland

    mock = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=list(FOCUSED_WINDOW_COMMAND), returncode=0, stdout=TERMINAL_OUTPUT, stderr=""
        )
    )
    monkeypatch.setattr(subprocess, "run", mock)
    monkeypatch.setattr(active_window_wayland.subprocess, "run", mock)
    return mock


def _warning_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """caplog に残った WARNING のログを返す。"""
    return [record for record in caplog.records if record.levelno == logging.WARNING]


def test_read_focused_wm_class(run: MagicMock) -> None:
    """拡張の返す wm_class_instance・wm_class を返す（正常系）。"""
    from voice_paste.integrations.keyboard.active_window_wayland import read_focused_wm_class

    # 実行
    result = read_focused_wm_class()

    # 検証
    assert result == ("gnome-terminal-server", "Gnome-terminal")
    assert tuple(run.call_args.args[0]) == FOCUSED_WINDOW_COMMAND
    assert run.call_args.kwargs["timeout"] == FOCUSED_WINDOW_TIMEOUT_SEC
    assert run.call_args.kwargs["check"] is True


def test_read_focused_wm_class_when_empty_values(run: MagicMock) -> None:
    """空の値を除いて返す（正常系）。"""
    from voice_paste.integrations.keyboard.active_window_wayland import read_focused_wm_class

    # 準備
    run.return_value = subprocess.CompletedProcess(
        args=list(FOCUSED_WINDOW_COMMAND),
        returncode=0,
        stdout="('{\"wm_class\":\"python3\",\"wm_class_instance\":\"\"}',)\n",
        stderr="",
    )

    # 実行
    result = read_focused_wm_class()

    # 検証
    assert result == ("python3",)


def test_read_focused_wm_class_when_extension_missing(
    run: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """拡張が無ければ空を返す（異常系）。"""
    from voice_paste.integrations.keyboard.active_window_wayland import read_focused_wm_class

    # 準備
    run.side_effect = subprocess.CalledProcessError(1, list(FOCUSED_WINDOW_COMMAND))
    caplog.set_level(logging.WARNING)

    # 実行
    result = read_focused_wm_class()

    # 検証
    assert result == ()
    assert len(_warning_logs(caplog)) == 1


def test_read_focused_wm_class_when_gdbus_missing(run: MagicMock) -> None:
    """gdbus が無ければ空を返す（異常系）。"""
    from voice_paste.integrations.keyboard.active_window_wayland import read_focused_wm_class

    # 準備
    run.side_effect = FileNotFoundError("gdbus")

    # 実行
    result = read_focused_wm_class()

    # 検証
    assert result == ()


def test_read_focused_wm_class_when_timeout(run: MagicMock) -> None:
    """応答が遅ければ空を返す（異常系）。"""
    from voice_paste.integrations.keyboard.active_window_wayland import read_focused_wm_class

    # 準備
    run.side_effect = subprocess.TimeoutExpired(list(FOCUSED_WINDOW_COMMAND), 1.0)

    # 実行
    result = read_focused_wm_class()

    # 検証
    assert result == ()


def test_read_focused_wm_class_when_malformed(run: MagicMock) -> None:
    """出力の書式が違えば空を返す（異常系）。"""
    from voice_paste.integrations.keyboard.active_window_wayland import read_focused_wm_class

    # 準備
    run.return_value = subprocess.CompletedProcess(
        args=list(FOCUSED_WINDOW_COMMAND), returncode=0, stdout="('not json',)\n", stderr=""
    )

    # 実行
    result = read_focused_wm_class()

    # 検証
    assert result == ()
