"""ui/windows/settings_shortcuts.py（ShortcutPanel の set_presets・add_row・collect・change_count・mark_saved・focus_field）の単体テスト。

画面を使用するため offscreen の QApplication（conftest の qapp）で動かす。
欄は画面設計の項目 ID（shortcut_hotkey_{n}・shortcut_preset_{n}・shortcut_remove_{n}・shortcut_empty）と行の shortcut_row_{n} の objectName で参照する。
用語集のプリセットの識別子は、テストでは文字列で指定する（GlossaryPanel の識別子と同じく、名前を変えても変わらない値）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QWidget

from voice_paste.shared.os_kind import OsKind

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from voice_paste.ui.windows.settings_shortcuts import ShortcutPanel

OTHER_HOTKEYS: tuple[str, ...] = ("<ctrl>+<alt>+d", "<ctrl>+<alt>+z", "<ctrl>+<alt>+q")
"""ほかのホットキー（録音開始・一時停止・取り消しの既定）。"""

PRESETS: list[tuple[object, str]] = [("default", "既定"), ("meeting", "会議")]
"""用語集のプリセットの識別子と名前の組の並び。"""


def _make_panel(
    *, os_kind: OsKind = OsKind.WINDOWS, other_hotkeys: Sequence[str] = OTHER_HOTKEYS
) -> ShortcutPanel:
    """OS とほかのホットキーを指定して一覧を作り、用語集のプリセットの一覧（補正に使用するのは既定）を入れる。"""
    from voice_paste.ui.windows.settings_shortcuts import ShortcutPanel

    panel = ShortcutPanel(os_kind, lambda: list(other_hotkeys))
    panel.set_presets(PRESETS, "default")
    return panel


def _set_rows(panel: ShortcutPanel, rows: list[tuple[str, str]]) -> None:
    """（キー, プリセットの名前）の行を一覧に入れる。"""
    from voice_paste.shared.settings import GlossaryPresetHotkeySettings

    panel.set_rows(
        [GlossaryPresetHotkeySettings(hotkey=hotkey, preset=preset) for hotkey, preset in rows]
    )


def _hotkey_edits(panel: ShortcutPanel) -> list[QLineEdit]:
    """キーの欄を行の順で返却する。"""
    found = panel.findChildren(QLineEdit, QRegularExpression("^shortcut_hotkey_"))
    return sorted(found, key=lambda edit: edit.objectName())


def _preset_combos(panel: ShortcutPanel) -> list[QComboBox]:
    """切り替える用語集のプリセットの選択欄を行の順で返却する。"""
    found = panel.findChildren(QComboBox, QRegularExpression("^shortcut_preset_"))
    return sorted(found, key=lambda combo: combo.objectName())


def _row(panel: ShortcutPanel, index: int) -> QWidget:
    """何行目かの行の部品（objectName が shortcut_row_{n}）を返却する。"""
    row = panel.findChild(QWidget, f"shortcut_row_{index}")
    assert row is not None, f"shortcut_row_{index} の行が無い"
    return row


def _press(edit: QLineEdit, key: Qt.Key) -> None:
    """キーの欄に Ctrl+Alt+{key} を押して入れる。"""
    QTest.keyClick(edit, key, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)


# === set_presets ===


def test_set_presets_when_renamed(qapp: QApplication) -> None:
    """名前を変えたプリセットを指す行は新しい名前になる（正常系）。"""
    # 準備
    panel = _make_panel()
    _set_rows(panel, [("<ctrl>+<alt>+1", "会議")])

    # 実行
    panel.set_presets([("default", "既定"), ("meeting", "打ち合わせ")], "default")

    # 検証
    assert panel.collect() == [{"hotkey": "<ctrl>+<alt>+1", "preset": "打ち合わせ"}]


def test_set_presets_when_removed(qapp: QApplication) -> None:
    """削除したプリセットを指す行は一覧から削除する（正常系）。"""
    # 準備
    panel = _make_panel()
    _set_rows(panel, [("<ctrl>+<alt>+1", "会議")])
    changed: list[int] = []
    panel.changed.connect(lambda: changed.append(1))
    panel.show()

    # 実行
    panel.set_presets([("default", "既定")], "default")

    # 検証
    assert _hotkey_edits(panel) == []
    empty = panel.findChild(QLabel, "shortcut_empty")
    assert empty is not None
    assert empty.isVisible()
    assert changed == [1]
    panel.hide()


# === add_row ===


def test_add_row(qapp: QApplication) -> None:
    """初期値の入った行を追加する（正常系）。"""
    # 準備
    panel = _make_panel()
    changed: list[int] = []
    panel.changed.connect(lambda: changed.append(1))

    # 実行
    panel.add_row()

    # 検証
    assert panel.collect() == [{"hotkey": "<ctrl>+<alt>+s", "preset": "既定"}]
    assert _row(panel, 0).property("added") is True
    assert changed == [1]


def test_add_row_when_default_key_used(qapp: QApplication) -> None:
    """初期値のキーが使用されていれば空にする（正常系）。"""
    # 準備
    panel = _make_panel(other_hotkeys=(*OTHER_HOTKEYS, "<ctrl>+<alt>+s"))

    # 実行
    panel.add_row()

    # 検証
    assert panel.collect() == [{"hotkey": "", "preset": "既定"}]


def test_add_row_when_linux(qapp: QApplication) -> None:
    """Linux の初期値のキーは Super+Alt+G（正常系）。"""
    # 準備
    panel = _make_panel(os_kind=OsKind.LINUX)

    # 実行
    panel.add_row()

    # 検証
    assert panel.collect()[0]["hotkey"] == "<cmd>+<alt>+g"


# === collect ===


def test_collect(qapp: QApplication) -> None:
    """行を pynput の書式とそのときの名前で返却する（正常系）。"""
    # 準備: Ctrl+Alt+S の行を入れて追加した行のキーを空にしてから、1 行目のキーを Ctrl+Alt+1 に変える
    panel = _make_panel()
    _set_rows(panel, [("<ctrl>+<alt>+s", "会議")])
    panel.add_row()
    _press(_hotkey_edits(panel)[0], Qt.Key.Key_1)

    # 実行
    collected = panel.collect()

    # 検証
    assert collected == [
        {"hotkey": "<ctrl>+<alt>+1", "preset": "会議"},
        {"hotkey": "", "preset": "既定"},
    ]


# === change_count ===


def test_change_count(qapp: QApplication) -> None:
    """追加・削除・キーかプリセットを変えた行を 1 件ずつ数える（正常系）。"""
    # 準備
    panel = _make_panel()
    _set_rows(
        panel,
        [("<ctrl>+<alt>+1", "既定"), ("<ctrl>+<alt>+2", "会議"), ("<ctrl>+<alt>+3", "会議")],
    )

    # 実行: 1 行目のキーを変え、2 行目を削除し、行を 1 つ追加する
    _press(_hotkey_edits(panel)[0], Qt.Key.Key_7)
    remove = panel.findChild(QAbstractButton, "shortcut_remove_1")
    assert remove is not None
    remove.click()
    panel.add_row()

    # 検証
    assert panel.change_count() == 3


def test_change_count_when_reverted(qapp: QApplication) -> None:
    """キーを変えてから元のキーに戻すと数えない（正常系）。"""
    # 準備
    panel = _make_panel()
    _set_rows(panel, [("<ctrl>+<alt>+1", "既定")])

    # 実行
    _press(_hotkey_edits(panel)[0], Qt.Key.Key_7)
    _press(_hotkey_edits(panel)[0], Qt.Key.Key_1)

    # 検証
    assert panel.change_count() == 0


# === mark_saved ===


def test_mark_saved(qapp: QApplication) -> None:
    """保存した行を基準にし直す（正常系）。"""
    # 準備
    panel = _make_panel()
    panel.add_row()

    # 実行
    panel.mark_saved()

    # 検証
    assert panel.change_count() == 0
    assert _row(panel, 0).property("added") is False


# === focus_field ===


def test_focus_field(qapp: QApplication) -> None:
    """指定の行の欄へフォーカスを移す（正常系）。"""
    # 準備
    panel = _make_panel()
    _set_rows(panel, [("<ctrl>+<alt>+1", "既定"), ("<ctrl>+<alt>+2", "会議")])
    panel.show()

    # 実行
    panel.focus_field(1, "preset")

    # 検証
    assert panel.focusWidget() is _preset_combos(panel)[1]
    panel.hide()
