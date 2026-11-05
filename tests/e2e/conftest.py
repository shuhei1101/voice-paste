"""E2E テストの共通フィクスチャ。実機のテストなので `--run-e2e` が無ければ skip する（ガードは tests/conftest.py）。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import pyperclip
import pytest
from PySide6.QtWidgets import QApplication

from tests.support.browser import EdgeBrowser, launch_edge
from tests.support.fixtures import (  # noqa: F401 フィクスチャとして使う
    haas_endpoint,
    openai_endpoint,
    receiver,
    start_inprocess,
    start_service,
)
from tests.support.inprocess import KeyLog
from tests.support.resident_app import (
    Case,
    RecordingInput,
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
        api_settings: str = "",
        legacy_settings: bool = False,
        port: int | None = None,
        prepare: Callable[[Path], None] | None = None,
        expect_exit: bool = False,
        wav_input: RecordingInput | None = None,
        keys: KeyLog | None = None,
        capture_browser: bool = False,
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
            api_settings=api_settings,
            legacy_settings=legacy_settings,
            port=port,
            prepare=prepare,
            expect_exit=expect_exit,
            wav_input=wav_input,
            keys=keys,
            capture_browser=capture_browser,
        )

    yield _run
    for data_dir in data_dirs:
        kill_service_processes_for(data_dir)


@pytest.fixture
def open_edge(tmp_path: Path) -> Iterator[Callable[..., EdgeBrowser]]:
    """Edge を偽のマイクで起動する関数を返す。起動した Edge は、テストの後に終わらせる。"""
    launched: list[EdgeBrowser] = []
    with ExitStack() as stack:

        def _open(*, fake_microphone_wav: Path | None = None) -> EdgeBrowser:
            """起動した Edge を返す（置き場所は起動した順の一時フォルダ）。"""
            profile = tmp_path / f"edge{len(launched)}"
            browser = stack.enter_context(
                launch_edge(profile, fake_microphone_wav=fake_microphone_wav)
            )
            launched.append(browser)
            return browser

        yield _open
