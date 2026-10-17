"""E2E テストの共通フィクスチャ。実機のテストなので `--run-e2e` が無ければ skip する（ガードは tests/conftest.py）。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pyperclip
import pytest
from PySide6.QtWidgets import QApplication

from tests.support.fixtures import receiver, start_inprocess, start_service  # noqa: F401 フィクスチャとして使う
from tests.support.inprocess import WavInput
from tests.support.resident_app import (
    Case,
    ResidentApp,
    kill_service_processes_for,
    run_resident_app,
)

CLIPBOARD_SENTINEL = "voice-paste-e2e-clipboard-sentinel"
"""録音の前にクリップボードへ置く目印の文字。"""


@pytest.fixture
def clipboard_sentinel() -> Iterator[str]:
    """クリップボードに目印を置き、テストの後に元の中身へ戻す。目印を返す。"""
    original = pyperclip.paste()
    pyperclip.copy(CLIPBOARD_SENTINEL)
    yield CLIPBOARD_SENTINEL
    pyperclip.copy(original)


@pytest.fixture
def run_app(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Callable[..., ResidentApp]]:
    """常駐アプリを pytest のプロセスの中で `main()` から起動し、ケースを進めて、結果を返す関数を返す。

    再起動で起動し直したプロセスは、テストの後に止める。
    """
    data_dirs: list[Path] = []

    def _run(
        case: Case,
        *,
        extra_settings: str = "",
        port: int | None = None,
        prepare: Callable[[Path], None] | None = None,
        expect_exit: bool = False,
        wav_input: WavInput | None = None,
    ) -> ResidentApp:
        """一時フォルダを置き場所にして起動し、case を進める。"""
        data_dir = tmp_path / f"app{len(data_dirs)}"
        data_dirs.append(data_dir)
        return run_resident_app(
            case,
            qapp=qapp,
            monkeypatch=monkeypatch,
            data_dir=data_dir,
            extra_settings=extra_settings,
            port=port,
            prepare=prepare,
            expect_exit=expect_exit,
            wav_input=wav_input,
        )

    yield _run
    for data_dir in data_dirs:
        kill_service_processes_for(data_dir)
