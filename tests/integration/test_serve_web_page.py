"""画面を配信する（GET /web/）の結合テスト。

本物の app を 127.0.0.1 の空きポートに立て、httpx で叩く。ゲートウェイを通した形（Host は localhost:{ポート}・トークン無し）で要求する。
"""

from __future__ import annotations

import logging
import re

import pytest

from tests.integration.helpers import WEB_ORIGIN, Stack


def _gateway_headers(stack: Stack, **extra: str) -> dict[str, str]:
    """ゲートウェイを通した画面の要求のヘッダー（Host は localhost:{ポート}、Origin 無し）に extra を足す。"""
    return {"Host": f"localhost:{stack.port}", **extra}


def test_normal(stack: Stack) -> None:
    """ゲートウェイを通した画面の要求に、画面の HTML を返す（正常系）。"""
    # 実行
    page = stack.http.get("/web/", headers=_gateway_headers(stack))
    asset_paths = re.findall(r'(?:src|href)="(assets/[^"]+)"', page.text)
    assets = [stack.http.get(f"/web/{path}", headers=_gateway_headers(stack)) for path in asset_paths]

    # 検証
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert len(asset_paths) >= 2
    assert [asset.status_code for asset in assets] == [200] * len(assets)


def test_normal_when_allowed_origin(stack: Stack) -> None:
    """許す Origin が付いた画面の素材の要求を通す（正常系）。"""
    # 実行
    response = stack.http.get(
        "/web/assets/style.css", headers=_gateway_headers(stack, Origin=WEB_ORIGIN)
    )

    # 検証
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_error_when_origin_not_allowed(stack: Stack, caplog: pytest.LogCaptureFixture) -> None:
    """許す Origin に無い Origin が付いた要求を断る（異常系）。"""
    # 準備
    caplog.set_level(logging.WARNING)

    # 実行
    response = stack.http.get("/web/", headers=_gateway_headers(stack, Origin="http://evil.example"))

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "http://evil.example" in caplog.text
    assert f"localhost:{stack.port}" in caplog.text


def test_error_when_host_not_loopback(stack: Stack) -> None:
    """Host が待ち受けのホストでない要求を断る（異常系）。"""
    # 実行
    response = stack.http.get("/web/", headers={"Host": "evil.example"})

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/web/assets/none.js", id="missing_file"),
        pytest.param("/web/assets/..%2F..%2Fsettings.toml", id="outside_directory"),
    ],
)
def test_error_when_asset_not_found(stack: Stack, path: str) -> None:
    """画面の置き場所に無いパスと、置き場所の外を指すパスを 404 にする（異常系）。"""
    # 実行
    response = stack.http.get(path, headers=_gateway_headers(stack))

    # 検証
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
