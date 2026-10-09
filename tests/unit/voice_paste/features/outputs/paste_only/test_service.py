"""features/outputs/paste_only/service.py（paste_only・inject_paste_only）の単体テスト。

クリップボード（copy）と貼り付けのキー（paste）は、呼ばれた順を 1 本の列で見られる Mock にして、順序と引数を確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from tests.unit.voice_paste.features.outputs.helpers import make_output_deps
from voice_paste.shared.errors import DeliveryError
from voice_paste.shared.types import TranscriptionOutcome


def _outcome() -> TranscriptionOutcome:
    """届ける結果（起こした文字「テスト」）を作る。"""
    return TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )


def test_paste_only() -> None:
    """コピーして貼り付ける（正常系）。"""
    from voice_paste.features.outputs.paste_only.service import paste_only

    # 準備
    parent = MagicMock()

    # 実行
    paste_only(_outcome(), None, copy=parent.copy, paste=parent.paste)

    # 検証
    assert parent.mock_calls == [call.copy("テスト"), call.paste()]


def test_paste_only_when_copy_failed() -> None:
    """クリップボードへ書けなければ貼り付けない（異常系）。"""
    from voice_paste.features.outputs.paste_only.service import paste_only

    # 準備
    copy = MagicMock(side_effect=DeliveryError("クリップボードへ書けない"))
    paste = MagicMock()

    # 実行・検証
    with pytest.raises(DeliveryError, match="クリップボードへ書けない"):
        paste_only(_outcome(), None, copy=copy, paste=paste)
    paste.assert_not_called()


# === inject_paste_only ===


def test_inject_paste_only() -> None:
    """copy・paste だけを渡す（正常系）。"""
    from voice_paste.features.outputs.paste_only.service import inject_paste_only

    # 準備
    deps = make_output_deps()

    # 実行
    injected = inject_paste_only(deps)

    # 検証
    assert set(injected) == {"copy", "paste"}
    assert injected["copy"] is deps.copy
    assert injected["paste"] is deps.paste
