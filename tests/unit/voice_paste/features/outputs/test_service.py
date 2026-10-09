"""features/outputs/service.py（deliver）の単体テスト。

出力先・プリセットの種類の関数（handler）は Mock にして、どれが呼ばれたかだけを確かめる。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

CALLBACK_URL = "http://127.0.0.1:9000/result"


def test_deliver_when_api_session() -> None:
    """API のセッションは呼び出し元へ返すだけ（正常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec, PresetKindSpec
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    callback = MagicMock()
    endpoint = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="callback", title="呼び出し元へ返す", handler=callback, api_only=True),
    ]
    preset_kinds = [PresetKindSpec(kind="endpoint", title="エンドポイントへ送る", handler=endpoint)]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行
    deliver(
        "api",
        None,
        None,
        CALLBACK_URL,
        outcome,
        enabled_ids=frozenset({"paste_and_send"}),
        outputs=outputs,
        preset_kinds=preset_kinds,
    )

    # 検証
    callback.assert_called_once_with(outcome, CALLBACK_URL)
    paste_and_send.assert_not_called()
    endpoint.assert_not_called()


def test_deliver_when_hotkey_session() -> None:
    """ホットキーのセッションは選んだ出力先へ届ける（正常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec, PresetKindSpec
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    paste_only = MagicMock()
    callback = MagicMock()
    endpoint = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="paste_only", title="貼り付けのみ", handler=paste_only),
        OutputSpec(id="callback", title="呼び出し元へ返す", handler=callback, api_only=True),
    ]
    preset_kinds = [PresetKindSpec(kind="endpoint", title="エンドポイントへ送る", handler=endpoint)]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行
    deliver(
        "hotkey",
        "paste_only",
        None,
        None,
        outcome,
        enabled_ids=frozenset({"paste_and_send", "paste_only"}),
        outputs=outputs,
        preset_kinds=preset_kinds,
    )

    # 検証
    paste_only.assert_called_once_with(outcome, None)
    paste_and_send.assert_not_called()
    callback.assert_not_called()
    endpoint.assert_not_called()


def test_deliver_when_output_disabled() -> None:
    """オフの出力先は届けない（異常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec
    from voice_paste.shared.errors import UnknownOutputError
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    copy_only = MagicMock()
    outputs = [
        OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send),
        OutputSpec(id="copy_only", title="コピーのみ", handler=copy_only),
    ]
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行・検証
    with pytest.raises(UnknownOutputError, match="copy_only"):
        deliver(
            "hotkey",
            "copy_only",
            None,
            None,
            outcome,
            enabled_ids=frozenset({"paste_and_send"}),
            outputs=outputs,
            preset_kinds=[],
        )
    paste_and_send.assert_not_called()
    copy_only.assert_not_called()


def test_deliver_when_preset() -> None:
    """選んだプリセットの種類の関数で届ける（正常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import OutputSpec, PresetKindSpec
    from voice_paste.shared.settings import EndpointPreset
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    paste_and_send = MagicMock()
    browser = MagicMock()
    endpoint = MagicMock()
    outputs = [OutputSpec(id="paste_and_send", title="貼り付けて送信", handler=paste_and_send)]
    preset_kinds = [
        PresetKindSpec(kind="browser", title="ブラウザ添付", handler=browser),
        PresetKindSpec(kind="endpoint", title="エンドポイントへ送る", handler=endpoint),
    ]
    preset = EndpointPreset(title="受け口", url="http://127.0.0.1:9000/hook")
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行
    deliver(
        "hotkey",
        None,
        preset,
        None,
        outcome,
        enabled_ids=frozenset({"paste_and_send"}),
        outputs=outputs,
        preset_kinds=preset_kinds,
    )

    # 検証
    endpoint.assert_called_once_with(outcome, preset)
    browser.assert_not_called()
    paste_and_send.assert_not_called()


def test_deliver_when_unknown_preset_kind() -> None:
    """一覧に無い種類のプリセットは届けない（異常系）。"""
    from voice_paste.features.outputs.service import deliver
    from voice_paste.features.outputs.types import PresetKindSpec
    from voice_paste.shared.errors import UnknownOutputError
    from voice_paste.shared.settings import EndpointPreset
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    browser = MagicMock()
    preset_kinds = [PresetKindSpec(kind="browser", title="ブラウザ添付", handler=browser)]
    preset = EndpointPreset(title="受け口", url="http://127.0.0.1:9000/hook")
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="てすと", error=None
    )

    # 実行・検証
    with pytest.raises(UnknownOutputError):
        deliver(
            "hotkey",
            None,
            preset,
            None,
            outcome,
            enabled_ids=frozenset(),
            outputs=[],
            preset_kinds=preset_kinds,
        )
    browser.assert_not_called()
