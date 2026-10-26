"""integrations/keyboard/sender.py（copy_to_clipboard）の外部疎通テスト。

実機のクリップボードへ書いて pyperclip で読み戻し、pyperclip のバージョンが上がって API が変わったことに気づけるようにする。
実行中はクリップボードの中身が変わり、終わりに実行前の中身へ戻す。クリップボードを持たない環境では skip する。
"""

from __future__ import annotations

from collections.abc import Iterator

import pyperclip
import pytest

TEXT = "voice-paste のテスト"


@pytest.fixture
def clipboard() -> Iterator[None]:
    """実行前のクリップボードの中身を控え、終わりに戻す。クリップボードを持たない環境では skip する。"""
    try:
        original = pyperclip.paste()
    except pyperclip.PyperclipException as error:
        pytest.skip(f"クリップボードを持たない環境のため実行しない（{error}）")

    yield

    pyperclip.copy(original)


def test_ext_copy_to_clipboard(clipboard: None) -> None:
    """copy_to_clipboard で書いた文字を pyperclip で読み戻せる（正常系）。"""
    from voice_paste.integrations.keyboard.sender import copy_to_clipboard

    # 実行
    copy_to_clipboard(TEXT)

    # 検証
    assert pyperclip.paste() == TEXT
