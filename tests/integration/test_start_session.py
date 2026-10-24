"""録音を開始する（POST /sessions）の結合テスト。

本物の app を 127.0.0.1 の空きポートに立て、httpx で叩く。マイク・システム音量・文字起こしのエンジンは偽物。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pytest

from tests.integration.helpers import VOLUME_BEFORE, Stack
from voice_paste.features.correction import pick_glossary_preset
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import (
    GlossaryPresetSettings,
    Settings,
    load_settings,
    save_settings,
)

BROWSER_REQUEST_HEADERS = [
    pytest.param({"Origin": "http://evil.example"}, id="origin"),
    pytest.param({"Host": "evil.example"}, id="host"),
]


def test_normal(stack: Stack) -> None:
    """画面を出さない録音を始め、セッションの ID を返す（正常系）。"""
    # 実行
    response = stack.post("/sessions", json_body={"callback_url": stack.receiver.url})

    # 検証
    assert response.status_code == 202
    assert response.json()["session_id"] == stack.session().id
    assert stack.state() == "recording"
    assert len(stack.microphone.streams) == 1


def test_normal_when_continuous(stack: Stack) -> None:
    """continuous を指定すると、完了が来るまで止めない録音を始め、セッションの ID を返す（正常系）。"""
    # 実行
    response = stack.post(
        "/sessions", json_body={"callback_url": stack.receiver.url, "continuous": True}
    )
    busy = stack.post("/sessions", json_body={"callback_url": stack.receiver.url})

    # 検証
    assert response.status_code == 202
    assert response.json()["session_id"] == stack.session().id
    assert stack.session().continuous is True
    assert stack.state() == "recording"
    assert len(stack.microphone.streams) == 1
    assert not stack.microphone.streams[0].closed
    assert busy.status_code == 409


def test_normal_when_glossary_preset(stack_with_settings: Callable[[Settings], Stack]) -> None:
    """glossary_preset で指定した用語集のプリセットをセッションに持たせて録音を始め、セッションの ID を返す（正常系）。"""
    # 準備（設定に用語集のプリセット「既定」と「会議」があり、設定で選んでいるのは「既定」）
    settings = SETTINGS_MODEL(
        glossary_presets=[
            GlossaryPresetSettings(name="既定", glossaries=[]),
            GlossaryPresetSettings(name="会議", glossaries=[]),
        ],
        active_glossary_preset="既定",
    )
    stack = stack_with_settings(settings)
    save_settings(stack.paths.settings_file, settings)

    # 実行
    response = stack.post(
        "/sessions", json_body={"callback_url": stack.receiver.url, "glossary_preset": "会議"}
    )

    # 検証（開始の後に settings.toml を読み直しても、設定で選んでいるプリセットは「既定」のまま）
    assert response.status_code == 202
    assert response.json()["session_id"] == stack.session().id
    assert stack.state() == "recording"
    assert stack.session().glossary_preset == "会議"
    reloaded = load_settings(stack.paths.settings_file, SETTINGS_MODEL)
    assert reloaded.active_glossary_preset == "既定"
    assert pick_glossary_preset(reloaded, stack.paths.settings_file.parent).name == "既定"


def test_error_when_glossary_preset_not_found(stack: Stack) -> None:
    """設定の一覧に無い用語集のプリセットを指定したら録音を始めない（異常系）。"""
    # 実行
    response = stack.post(
        "/sessions",
        json_body={"callback_url": stack.receiver.url, "glossary_preset": "無いプリセット"},
    )

    # 検証
    assert response.status_code == 400
    assert "無いプリセット" in response.json()["detail"]
    assert stack.microphone.streams == []
    assert stack.state() is None


def test_error_when_callback_not_allowed(stack: Stack) -> None:
    """許可していない返送先では録音を始めない（異常系）。"""
    # 実行
    response = stack.post("/sessions", json_body={"callback_url": "http://example.com/result"})

    # 検証
    assert response.status_code == 400
    assert stack.microphone.streams == []
    assert stack.state() is None


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no_authorization"),
        pytest.param({"Authorization": "Bearer wrong-token"}, id="wrong_token"),
    ],
)
def test_error_when_token_mismatch(
    stack: Stack, caplog: pytest.LogCaptureFixture, headers: dict[str, str]
) -> None:
    """トークンが合わなければ録音を始めない（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)

    # 実行
    response = stack.post(
        "/sessions",
        json_body={"callback_url": stack.receiver.url},
        headers=headers,
        authorized=False,
    )

    # 検証
    assert response.status_code == 401
    assert stack.microphone.streams == []
    assert "Host" in caplog.text
    assert stack.token not in caplog.text


@pytest.mark.parametrize("headers", BROWSER_REQUEST_HEADERS)
def test_error_when_browser_request(
    stack: Stack, caplog: pytest.LogCaptureFixture, headers: dict[str, str]
) -> None:
    """Origin の付いた要求と、Host が待ち受けのホストでない要求を断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)

    # 実行
    response = stack.post(
        "/sessions", json_body={"callback_url": stack.receiver.url}, headers=headers
    )

    # 検証
    assert response.status_code == 403
    assert stack.microphone.streams == []
    assert "Host" in caplog.text
    assert stack.token not in caplog.text


def test_error_when_busy(stack: Stack) -> None:
    """ほかの録音・文字起こしの処理中は開始を断る（異常系）。"""
    # 準備
    stack.manager.start("hotkey")

    # 実行
    response = stack.post("/sessions", json_body={"callback_url": stack.receiver.url})

    # 検証
    assert response.status_code == 409
    assert stack.state() == "recording"
    assert stack.session().entry == "hotkey"
    assert len(stack.microphone.streams) == 1


def test_error_when_microphone_unavailable(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    """マイクを開けなければ音量を戻して断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    stack.microphone.open_error = OSError("マイクが見つからない")

    # 実行
    response = stack.post("/sessions", json_body={"callback_url": stack.receiver.url})

    # 検証
    assert response.status_code == 503
    assert stack.volume.level == VOLUME_BEFORE
    assert stack.state() is None
    stack.microphone.open_error = None
    assert stack.post("/sessions", json_body={"callback_url": stack.receiver.url}).status_code == 202
    assert "マイクが見つからない" in caplog.text
