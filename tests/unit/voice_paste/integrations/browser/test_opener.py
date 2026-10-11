"""integrations/browser/opener.py（open_app_window）の単体テスト。

shutil.which・Path.exists・subprocess.Popen・os.startfile は Mock に差し替え、実機のブラウザは起動しない。
os.startfile は Windows にしか無いため、属性が無い環境でも差し替えられるよう raising=False で置く。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from voice_paste.shared.errors import DeliveryError

URL = "https://chatgpt.com"


@pytest.fixture
def which(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """shutil.which を差し替えた Mock を返す（既定は msedge が PATH に無い）。"""
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
def startfile(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """os.startfile を差し替えた Mock を返す（Windows 以外には属性が無いため raising=False）。"""
    mock = MagicMock()
    monkeypatch.setattr(os, "startfile", mock, raising=False)
    return mock


def _existing_paths(monkeypatch: pytest.MonkeyPatch, *existing: str) -> None:
    """Path.exists が、existing に挙げたパスだけ True を返すようにする。"""
    paths = {str(Path(path)) for path in existing}
    monkeypatch.setattr(Path, "exists", lambda self, **_kwargs: str(self) in paths)


def test_open_app_window(which: MagicMock, popen: MagicMock, startfile: MagicMock) -> None:
    """PATH に msedge があれば --app で開く（正常系）。"""
    from voice_paste.integrations.browser.opener import open_app_window

    # 準備
    which.return_value = "msedge"

    # 実行
    open_app_window(URL)

    # 検証
    which.assert_called_once_with("msedge")
    popen.assert_called_once()
    assert popen.call_args.args[0] == ["msedge", "--app=https://chatgpt.com"]
    startfile.assert_not_called()


def test_open_app_window_when_installed_path(
    which: MagicMock,
    popen: MagicMock,
    startfile: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATH に無ければ既定の置き場所の Edge で開く（正常系）。"""
    from voice_paste.integrations.browser.opener import EDGE_PATHS, open_app_window

    # 準備
    _existing_paths(monkeypatch, EDGE_PATHS[1])

    # 実行
    open_app_window(URL)

    # 検証
    popen.assert_called_once()
    assert popen.call_args.args[0] == [EDGE_PATHS[1], "--app=https://chatgpt.com"]
    startfile.assert_not_called()


def test_open_app_window_when_edge_missing(
    which: MagicMock,
    popen: MagicMock,
    startfile: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge が見つからなければ既定のブラウザで開く（正常系）。"""
    from voice_paste.integrations.browser.opener import open_app_window

    # 準備
    _existing_paths(monkeypatch)

    # 実行
    open_app_window(URL)

    # 検証
    startfile.assert_called_once_with(URL)
    popen.assert_not_called()


def test_open_app_window_when_failed(which: MagicMock, popen: MagicMock) -> None:
    """Edge を起動できなければ DeliveryError にする（異常系）。"""
    from voice_paste.integrations.browser.opener import open_app_window

    # 準備
    which.return_value = "msedge"
    popen.side_effect = OSError("起動できない")

    # 実行・検証
    with pytest.raises(
        DeliveryError, match=r"^ブラウザ添付のプリセットの画面を開けませんでした（.*起動できない"
    ) as exc_info:
        open_app_window(URL)
    assert "AI チャット" not in str(exc_info.value)
