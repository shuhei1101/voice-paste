"""用語集のプリセットの一覧を返す（GET /web/glossary-presets）の結合テスト。

本物の app を 127.0.0.1 の空きポートに立て、httpx で叩く。ゲートウェイを通した構成（Host は localhost:{ポート}・トークン無し）で呼ぶ。
設定は一式に差した Settings から読み、呼ぶたびに今の設定を引く。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.integration.helpers import Stack
from voice_paste.main import SETTINGS_MODEL
from voice_paste.shared.settings import GlossaryPresetSettings, GlossarySettings


def test_normal(web_stack: Callable[..., Stack], tmp_path: Path) -> None:
    """設定の並びのままのプリセットの名前と、設定で選んでいるプリセットの名前を返す（正常系）。"""
    # 準備: プリセット「既定」「会議」をこの並びで入れ、選んでいるのを「会議」にする
    settings = SETTINGS_MODEL(
        glossaries=[GlossarySettings(name="社内用語", path=tmp_path / "company.csv")],
        glossary_presets=[
            GlossaryPresetSettings(name="既定", glossaries=[]),
            GlossaryPresetSettings(name="会議", glossaries=["社内用語"]),
        ],
        active_glossary_preset="会議",
    )
    stack = web_stack(worker=False, settings=settings)

    # 実行
    response = stack.get_glossary_presets()

    # 検証: 名前だけを返し、用語集の名前は含まない
    assert response.status_code == 200
    assert response.json() == {"presets": ["既定", "会議"], "active": "会議"}
    assert "社内用語" not in response.text

    # 実行: 設定画面で「会議」を削除して選び直した後に呼ぶ
    stack.web.settings = settings.model_copy(
        update={
            "glossary_presets": [GlossaryPresetSettings(name="既定", glossaries=[])],
            "active_glossary_preset": "既定",
        }
    )
    reloaded = stack.get_glossary_presets()

    # 検証: 変わった内容を返す
    assert reloaded.json() == {"presets": ["既定"], "active": "既定"}


def test_normal_when_presets_not_configured(web_stack: Callable[..., Stack]) -> None:
    """glossary_presets のキーが無い設定では「既定」の 1 件を返す（正常系）。"""
    # 準備: glossary_presets と active_glossary_preset を持たない設定
    stack = web_stack(worker=False, settings=SETTINGS_MODEL())

    # 実行
    response = stack.get_glossary_presets()

    # 検証
    assert response.status_code == 200
    assert response.json() == {"presets": ["既定"], "active": "既定"}


def test_error_when_origin_not_allowed(
    web_stack: Callable[..., Stack], caplog: pytest.LogCaptureFixture
) -> None:
    """許す Origin に無い Origin が付いた要求を断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)
    settings = SETTINGS_MODEL(
        glossary_presets=[GlossaryPresetSettings(name="秘密の名前", glossaries=[])],
        active_glossary_preset="秘密の名前",
    )
    stack = web_stack(worker=False, settings=settings)

    # 実行
    response = stack.get_glossary_presets(origin="http://evil.example")

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "秘密の名前" not in response.text
    assert f"localhost:{stack.port}" in caplog.text
    assert "http://evil.example" in caplog.text


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param(None, id="without_origin"),
        pytest.param("http://evil.example", id="not_allowed_origin"),
    ],
)
def test_error_when_running_on_linux(linux_stack: Stack, origin: str | None) -> None:
    """常駐サービスが Linux で動いているときは、Origin によらず 404 を返す（異常系）。"""
    # 実行
    response = linux_stack.get_glossary_presets(origin=origin)

    # 検証
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
