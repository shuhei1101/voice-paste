"""features/outputs/copy_only/service.py（copy_only・inject_copy_only）の単体テスト。

クリップボード（copy）は Mock にして、書く文字を確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.unit.voice_paste.features.outputs.helpers import make_output_deps
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


def test_inject_copy_only() -> None:
    """copy だけを渡す（正常系）。"""
    from voice_paste.features.outputs.copy_only.service import inject_copy_only

    # 準備
    deps = make_output_deps()

    # 実行
    injected = inject_copy_only(deps)

    # 検証
    assert set(injected) == {"copy"}
    assert injected["copy"] is deps.copy
