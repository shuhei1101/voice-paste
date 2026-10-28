"""integrations/browser/opener_linux.py（open_app_window_linux）の単体テスト。

shutil.which・subprocess.Popen・webbrowser.open は Mock に差し替え、実機のブラウザは起動しない。
"""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from unittest.mock import MagicMock

import pytest

from voice_paste.shared.errors import DeliveryError

URL = "https://chatgpt.com"


@pytest.fixture
def which(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """shutil.which を差し替えた Mock を返す（既定はどのブラウザも PATH に無い）。"""
    mock = MagicMock(return_value=None)
    monkeypatch.setattr(shutil, "which", mock)
    return mock


@pytest.fixture
def popen(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """subprocess.Popen を差し替えた Mock を返す。"""
    mock = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock)
    return mock


@pytest.fixture
def browser_open(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """webbrowser.open を差し替えた Mock を返す（既定は開けた）。"""
    mock = MagicMock(return_value=True)
    monkeypatch.setattr(webbrowser, "open", mock)
    return mock


def test_open_app_window_linux(
    which: MagicMock, popen: MagicMock, browser_open: MagicMock
) -> None:
    """先に見つかった Chromium 系の --app で開く（正常系）。"""
    from voice_paste.integrations.browser.opener_linux import open_app_window_linux

    # 準備: 並びの後ろの microsoft-edge と、前の chromium だけが PATH にある
    which.side_effect = lambda name: {
        "chromium": "/usr/bin/chromium",
        "microsoft-edge": "/usr/bin/microsoft-edge",
    }.get(name)

    # 実行
    open_app_window_linux(URL)

    # 検証
    popen.assert_called_once()
    assert popen.call_args.args[0] == ["/usr/bin/chromium", "--app=https://chatgpt.com"]
    browser_open.assert_not_called()


def test_open_app_window_linux_when_browser_missing(
    which: MagicMock, popen: MagicMock, browser_open: MagicMock
) -> None:
    """Chromium 系が無ければ既定のブラウザで開く（正常系）。"""
    from voice_paste.integrations.browser.opener_linux import open_app_window_linux

    # 実行
    open_app_window_linux(URL)

    # 検証
    browser_open.assert_called_once_with(URL)
    popen.assert_not_called()


def test_open_app_window_linux_when_no_browser(which: MagicMock, browser_open: MagicMock) -> None:
    """既定のブラウザも開けなければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.browser.opener_linux import open_app_window_linux

    # 準備
    browser_open.return_value = False

    # 実行・検証
    with pytest.raises(DeliveryError, match=r"^ブラウザ添付のプリセットの画面を開けませんでした（"):
        open_app_window_linux(URL)


def test_open_app_window_linux_when_failed(which: MagicMock, popen: MagicMock) -> None:
    """見つかったブラウザを起動できなければ DeliveryError にし、元の例外を連鎖して残す（異常系）。"""
    from voice_paste.integrations.browser.opener_linux import open_app_window_linux

    # 準備
    which.return_value = "/usr/bin/chromium"
    cause = OSError("起動できない")
    popen.side_effect = cause

    # 実行・検証
    with pytest.raises(
        DeliveryError, match=r"^ブラウザ添付のプリセットの画面を開けませんでした（.*起動できない"
    ) as exc_info:
        open_app_window_linux(URL)
    assert exc_info.value.__cause__ is cause
