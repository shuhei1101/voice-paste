"""E2E テストの共通フィクスチャ。実機のテストなので `--run-e2e` が無ければ skip する（ガードは tests/conftest.py）。"""

from __future__ import annotations

from collections.abc import Iterator

import pyperclip
import pytest

from tests.support.fixtures import receiver, start_service  # noqa: F401 フィクスチャとして使う

CLIPBOARD_SENTINEL = "voice-paste-e2e-clipboard-sentinel"
"""録音の前にクリップボードへ置く目印の文字。"""


@pytest.fixture
def clipboard_sentinel() -> Iterator[str]:
    """クリップボードに目印を置き、テストの後に元の中身へ戻す。目印を返す。"""
    original = pyperclip.paste()
    pyperclip.copy(CLIPBOARD_SENTINEL)
    yield CLIPBOARD_SENTINEL
    pyperclip.copy(original)
