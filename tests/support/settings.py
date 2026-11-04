"""結合テスト・E2E・非機能要件テストで設定を組み立てる関数。

設定のモデルは表のまとまりの既定値を持たないため、リポジトリの config/defaults.yaml を読んだ既定の設定に、
テストの値を重ねて組み立てる（単体テストと同じ組み立てを使い回す）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.unit.voice_paste.settings_helpers import (
    DEFAULTS_FILE,
    load_test_default_settings,
    make_test_document,
    make_test_settings,
)

if TYPE_CHECKING:
    from voice_paste.shared.settings import OutputSettingsBase, Settings

__all__ = [
    "DEFAULTS_FILE",
    "default_output",
    "load_test_default_settings",
    "make_settings",
    "make_test_document",
    "make_test_settings",
]


def default_output(output_id: str, **values: Any) -> OutputSettingsBase:
    """既定の設定の出力先 output_id に、values の項目を替えたコピーを返す。"""
    output = next(
        output for output in load_test_default_settings().outputs if output.id == output_id
    )
    return output.model_copy(update=values)


def make_settings(**groups: Any) -> Settings:
    """既定の設定に、まとまりごとの値を重ねて検証した設定を返す。表のまとまりは dict でキーごとに重ね、一覧と値は丸ごと替える。"""
    return make_test_settings(groups)
