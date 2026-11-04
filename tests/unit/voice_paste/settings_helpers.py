"""単体テストで設定を組み立てる関数。

設定のモデルは表のまとまりの既定値を持たないため、リポジトリの config/defaults.yaml を読んだ既定の設定に、
テストの値を重ねて組み立てる。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from voice_paste.shared.settings import Settings

    MakeSettings = Callable[..., Settings]
    """make_test_settings と同じ引数で設定を作る関数（conftest の make_settings）。"""

REPO_ROOT = Path(__file__).resolve().parents[3]
"""リポジトリの直下。"""

DEFAULTS_FILE = REPO_ROOT / "config" / "defaults.yaml"
"""リポジトリの既定値のファイル。"""


def load_test_default_settings() -> Settings:
    """リポジトリの既定値のファイルを、アプリが使う設定のモデルで読んだ既定の設定を返す。"""
    # テストの本体で import し、実装が無いときはそのテストが ImportError で落ちるようにする
    from voice_paste.main import SETTINGS_MODEL
    from voice_paste.shared.settings import load_default_settings

    return load_default_settings(DEFAULTS_FILE, SETTINGS_MODEL)


def _overlay(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """base に overrides を重ねた新しい dict を返す。表はキーごとに重ね、一覧と値は丸ごと替える。"""
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        # 両方が表のキーか
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            # そう: 中のキーごとに重ねる
            merged[key] = _overlay(merged[key], value)
        else:
            # それ以外: 渡した値で丸ごと替える
            merged[key] = copy.deepcopy(value)
    return merged


def make_test_document(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """既定の設定を JSON にした dict に、設定と同じ構造の dict を重ねて返す（検証しない）。"""
    defaults = load_test_default_settings()
    return _overlay(defaults.model_dump(mode="json"), overrides or {})


def make_test_settings(overrides: Mapping[str, Any] | None = None, /, **fields: Any) -> Settings:
    """既定の設定に、設定と同じ構造の dict（JSON にした値）を重ね、一番上の項目を fields の値で替えて検証した設定を返す。"""
    from voice_paste.main import SETTINGS_MODEL

    document = make_test_document(overrides)
    document.update(fields)
    return SETTINGS_MODEL.model_validate(document)
