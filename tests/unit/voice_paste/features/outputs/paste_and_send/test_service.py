"""features/outputs/paste_and_send/service.py（paste_and_send・read_enter_delay_sec・inject_paste_and_send）の単体テスト。

クリップボード（copy）・貼り付けのキー（paste）・Enter（send_enter）・間（sleep）は、
呼ばれた順を 1 本の列で見られる Mock にして、順序と引数を確かめる。
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


def test_paste_and_send() -> None:
    """コピー・貼り付け・待ち・Enter の順に送る（正常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import paste_and_send

    # 準備
    parent = MagicMock()
    get_enter_delay_sec = MagicMock(return_value=0.5)

    # 実行
    paste_and_send(
        _outcome(),
        None,
        copy=parent.copy,
        paste=parent.paste,
        send_enter=parent.send_enter,
        sleep=parent.sleep,
        get_enter_delay_sec=get_enter_delay_sec,
    )

    # 検証
    assert parent.mock_calls == [
        call.copy("テスト"),
        call.paste(),
        call.sleep(0.5),
        call.send_enter(),
    ]


def test_paste_and_send_when_copy_failed() -> None:
    """クリップボードへ書けなければキーを送らない（異常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import paste_and_send

    # 準備
    copy = MagicMock(side_effect=DeliveryError("クリップボードへ書けない"))
    paste = MagicMock()
    send_enter = MagicMock()
    sleep = MagicMock()
    get_enter_delay_sec = MagicMock(return_value=0.5)

    # 実行・検証
    with pytest.raises(DeliveryError, match="クリップボードへ書けない"):
        paste_and_send(
            _outcome(),
            None,
            copy=copy,
            paste=paste,
            send_enter=send_enter,
            sleep=sleep,
            get_enter_delay_sec=get_enter_delay_sec,
        )
    paste.assert_not_called()
    send_enter.assert_not_called()


# === read_enter_delay_sec ===


def test_read_enter_delay_sec() -> None:
    """貼り付けて送信の秒数を返す（正常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import read_enter_delay_sec
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.shared.settings import Settings

    # 準備
    settings = Settings(outputs=[PasteAndSendSettings(enter_delay_sec=0.2)])

    # 実行
    seconds = read_enter_delay_sec(settings)

    # 検証
    assert seconds == 0.2


def test_read_enter_delay_sec_when_missing() -> None:
    """一覧に無ければ既定値を返す（正常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import read_enter_delay_sec
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.shared.settings import Settings

    # 準備
    settings = Settings(outputs=[PasteOnlySettings()])

    # 実行
    seconds = read_enter_delay_sec(settings)

    # 検証
    assert seconds == 0.5


# === inject_paste_and_send ===


def test_inject_paste_and_send() -> None:
    """呼ぶたびに今の設定の秒数を返す関数を渡す（正常系）。"""
    from voice_paste.features.outputs.paste_and_send.service import inject_paste_and_send
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.shared.settings import Settings

    # 準備
    get_settings = MagicMock(
        return_value=Settings(outputs=[PasteAndSendSettings(enter_delay_sec=0.2)])
    )
    deps = make_output_deps(get_settings=get_settings)

    # 実行: 取り出した後に設定を差し替え、前後で秒数を読む
    injected = inject_paste_and_send(deps)
    seconds_before = injected["get_enter_delay_sec"]()
    get_settings.return_value = Settings(outputs=[PasteAndSendSettings(enter_delay_sec=1.0)])
    seconds_after = injected["get_enter_delay_sec"]()

    # 検証
    assert set(injected) == {"copy", "paste", "send_enter", "sleep", "get_enter_delay_sec"}
    assert injected["copy"] is deps.copy
    assert injected["paste"] is deps.paste
    assert injected["send_enter"] is deps.send_enter
    assert injected["sleep"] is deps.sleep
    assert seconds_before == 0.2
    assert seconds_after == 1.0
