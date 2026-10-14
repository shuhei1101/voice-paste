"""features/outputs/copy_only/service.py（copy_only・inject_copy_only）の単体テスト。

クリップボード（copy）とコピーの完了の知らせ（notify_copied）は Mock にして、書く文字と呼ぶ順を確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from tests.unit.voice_paste.features.outputs.helpers import make_output_deps
from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome


def test_copy_only() -> None:
    """クリップボードへ書き、完了を知らせる（正常系）。"""
    from voice_paste.features.outputs.copy_only.service import copy_only

    # 準備
    parent = MagicMock()
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )

    # 実行
    copy_only(outcome, None, copy=parent.copy, notify_copied=parent.notify_copied)

    # 検証
    assert parent.mock_calls == [call.copy("テスト"), call.notify_copied("テスト")]


def test_copy_only_when_copy_failed() -> None:
    """クリップボードへ書けなければ完了を知らせない（異常系）。"""
    from voice_paste.features.outputs.copy_only.service import copy_only

    # 準備
    copy = MagicMock(side_effect=DeliveryError("クリップボードへ書けない"))
    notify_copied = MagicMock()
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )

    # 実行・検証
    with pytest.raises(DeliveryError, match="クリップボードへ書けない"):
        copy_only(outcome, None, copy=copy, notify_copied=notify_copied)
    notify_copied.assert_not_called()


def test_inject_copy_only() -> None:
    """copy・notify_copied だけを渡す（正常系）。"""
    from voice_paste.features.outputs.copy_only.service import inject_copy_only

    # 準備
    deps = make_output_deps()

    # 実行
    injected = inject_copy_only(deps)

    # 検証
    assert set(injected) == {"copy", "notify_copied"}
    assert injected["copy"] is deps.copy
    assert injected["notify_copied"] is deps.notify_copied
