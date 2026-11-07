"""haas_server/app.py（create_app・parse_tuning）の単体テスト。API の流れは結合テスト（tests/integration/haas_server/）が持つ。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fastapi.testclient import TestClient

PORT = 47824


def test_create_app_when_host_not_allowed() -> None:
    """Host が合わない要求を断る（異常系）。"""
    from haas_server.app import HaasEngine, create_app

    # 準備
    engine = HaasEngine(
        model_name="m",
        dtype="auto",
        device="cuda",
        transcribe=MagicMock(return_value="文字"),
        transcribe_longform=MagicMock(return_value="文字"),
        build_vocabulary=MagicMock(),
    )
    client = TestClient(create_app(engine, port=PORT, request_shutdown=MagicMock()))

    # 実行
    response = client.get("/health", headers={"Host": f"evil.example:{PORT}"})

    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_parse_tuning() -> None:
    """全ての項目を読む（正常系）。"""
    from haas_server.app import TranscribeOptions, parse_tuning

    # 準備
    fields = {
        "short_audio_limit_sec": "20",
        "batch_size": "8",
        "alpha": "3.0",
        "guard": "false",
        "chunk_sec": "15",
        "search_sec": "1",
        "window_sec": "0.05",
        "separator": "。",
    }

    # 実行
    result = parse_tuning(fields)

    # 検証
    assert result == TranscribeOptions(
        short_audio_limit_sec=20.0,
        batch_size=8,
        alpha=3.0,
        guard=False,
        chunk_sec=15.0,
        search_sec=1.0,
        window_sec=0.05,
        separator="。",
    )


def test_parse_tuning_when_missing() -> None:
    """無い項目は既定値（正常系）。"""
    from haas_server.app import TranscribeOptions, parse_tuning

    # 準備
    fields: dict[str, str | None] = {
        "short_audio_limit_sec": None,
        "batch_size": None,
        "alpha": None,
        "guard": None,
        "chunk_sec": None,
        "search_sec": None,
        "window_sec": None,
        "separator": None,
    }

    # 実行
    result = parse_tuning(fields)

    # 検証
    assert result == TranscribeOptions()


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        pytest.param({"batch_size": "0"}, "batch_size", id="batch_size_zero"),
        pytest.param({"chunk_sec": "0.5"}, "chunk_sec", id="chunk_sec_below"),
        pytest.param({"window_sec": "nan"}, "window_sec", id="window_sec_nan"),
    ],
)
def test_parse_tuning_when_out_of_range(fields: dict[str, str | None], field: str) -> None:
    """範囲の外（異常系）。"""
    from haas_server.app import TuningValueError, parse_tuning

    # 実行・検証
    with pytest.raises(TuningValueError) as exc_info:
        parse_tuning(fields)
    assert exc_info.value.field == field


def test_parse_tuning_when_guard_invalid() -> None:
    """guard が true でも false でもない（異常系）。"""
    from haas_server.app import TuningValueError, parse_tuning

    # 実行・検証
    with pytest.raises(TuningValueError) as exc_info:
        parse_tuning({"guard": "yes"})
    assert exc_info.value.field == "guard"


def test_parse_tuning_when_not_number() -> None:
    """数値に読めない（異常系）。"""
    from haas_server.app import TuningValueError, parse_tuning

    # 実行・検証
    with pytest.raises(TuningValueError) as exc_info:
        parse_tuning({"alpha": "abc"})
    assert exc_info.value.field == "alpha"


def test_parse_tuning_when_separator_too_long() -> None:
    """separator が長い（異常系）。"""
    from haas_server.app import TuningValueError, parse_tuning

    # 実行・検証
    with pytest.raises(TuningValueError) as exc_info:
        parse_tuning({"separator": "あ" * 17})
    assert exc_info.value.field == "separator"
