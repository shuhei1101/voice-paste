"""ui/windows/settings_presets.py（PresetListPanel の collect・add_preset と並べ替え）の単体テスト。

画面を使うため offscreen の QApplication（conftest の qapp）で動かす。
一覧は 1 つの種類（kind）だけを受け持つ。ボタンは画面設計の項目 ID（preset_down_{n}）の objectName の前方一致で引く。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import QAbstractButton

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.ui.windows.settings_presets import PresetListPanel


def _buttons(panel: PresetListPanel, prefix: str) -> list[QAbstractButton]:
    """一覧の中の objectName が prefix で始まるボタンを、名前の順で返す。"""
    pattern = QRegularExpression(f"^{prefix}")
    found = panel.findChildren(QAbstractButton, pattern)
    return sorted(found, key=lambda button: button.objectName())


def test_preset_list_panel_collect(qapp: QApplication) -> None:
    """入れたプリセットをそのまま集める（正常系）。"""
    from voice_paste.shared.settings import EndpointPreset
    from voice_paste.ui.windows.settings_presets import PresetListPanel

    # 準備
    panel = PresetListPanel("endpoint")
    panel.set_presets(
        [
            EndpointPreset(
                title="受け口 A",
                url="http://127.0.0.1:9000/a",
                hotkey="<ctrl>+<alt>+4",
                authorization="Bearer x",
            ),
            EndpointPreset(title="受け口 B", url="http://127.0.0.1:9000/b"),
        ]
    )

    # 実行
    collected = panel.collect()

    # 検証
    assert [preset["title"] for preset in collected] == ["受け口 A", "受け口 B"]
    assert [preset["kind"] for preset in collected] == ["endpoint", "endpoint"]
    assert collected[0]["hotkey"] == "<ctrl>+<alt>+4"
    assert collected[0]["authorization"] == "Bearer x"
    assert collected[1]["hotkey"] == ""


def test_preset_list_panel_move(qapp: QApplication) -> None:
    """下へで並びを入れ替える（正常系）。"""
    from voice_paste.shared.settings import BrowserPreset
    from voice_paste.ui.windows.settings_presets import PresetListPanel

    # 準備
    panel = PresetListPanel("browser")
    panel.set_presets(
        [
            BrowserPreset(title="A", url="https://a.example"),
            BrowserPreset(title="B", url="https://b.example"),
        ]
    )

    # 実行（A の「下へ」を押す）
    _buttons(panel, "preset_down_")[0].click()

    # 検証
    assert [preset["title"] for preset in panel.collect()] == ["B", "A"]


def test_preset_list_panel_add_preset(qapp: QApplication) -> None:
    """足したプリセットは有効で Enter まで送る（正常系）。"""
    from voice_paste.ui.windows.settings_presets import PresetListPanel

    # 準備
    panel = PresetListPanel("browser")
    changed_count: list[int] = []
    panel.changed.connect(lambda: changed_count.append(1))

    # 実行
    panel.add_preset()

    # 検証
    collected = panel.collect()
    assert len(collected) == 1
    assert collected[0]["kind"] == "browser"
    assert collected[0]["enabled"] is True
    assert collected[0]["send_enter"] is True
    assert collected[0]["title"] == ""
    assert collected[0]["url"] == ""
    assert collected[0]["hotkey"] == ""
    assert changed_count == [1]
