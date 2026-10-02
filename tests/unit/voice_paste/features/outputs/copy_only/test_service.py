"""features/outputs/copy_only/service.py（copy_only）の単体テスト。

クリップボード（copy）は Mock にして、書く文字を確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from voice_paste.shared.types import TranscriptionOutcome


def test_copy_only() -> None:
    """クリップボードへ書くだけ（正常系）。"""
    from voice_paste.features.outputs.copy_only.service import copy_only

    # 準備
    copy = MagicMock()
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )

    # 実行
    copy_only(outcome, None, copy=copy)

    # 検証
    copy.assert_called_once_with("テスト")
