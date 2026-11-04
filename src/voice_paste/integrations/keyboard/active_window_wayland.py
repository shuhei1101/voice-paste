"""Linux の Wayland のセッションの、フォーカスしているウィンドウの wm_class の読み取り。GNOME Shell の拡張 Focused Window D-Bus に触れるのはこのファイルだけ。"""

from __future__ import annotations

import ast
import json
import logging
import subprocess

logger = logging.getLogger(__name__)

FOCUSED_WINDOW_COMMAND: tuple[str, ...] = (
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.Shell",
    "--object-path",
    "/org/gnome/shell/extensions/FocusedWindow",
    "--method",
    "org.gnome.shell.extensions.FocusedWindow.Get",
)
"""拡張 Focused Window D-Bus の Get をセッションバスで呼ぶ gdbus の引数。"""

FOCUSED_WINDOW_TIMEOUT_SEC: float = 1.0
"""gdbus の応答を待つ秒数。超えたら読めなかったとして設定の貼り付けのキーを送信する。"""

WM_CLASS_KEYS: tuple[str, ...] = ("wm_class_instance", "wm_class")
"""拡張の返す JSON から読むキー（返す順）。"""


def read_focused_wm_class() -> tuple[str, ...]:
    """フォーカスしているウィンドウの（wm_class_instance, wm_class）のうち空でないものを返す。読めないときは空を返し、貼り付けを止めない。"""
    try:
        # 1. 拡張の Get を gdbus で呼ぶ
        completed = subprocess.run(
            FOCUSED_WINDOW_COMMAND,
            capture_output=True,
            text=True,
            check=True,
            timeout=FOCUSED_WINDOW_TIMEOUT_SEC,
        )

        # 2. `('{...}',)` の GVariant の書式をタプルにし、先頭の文字列を JSON として読む
        window = json.loads(ast.literal_eval(completed.stdout.strip())[0])
    except (OSError, subprocess.SubprocessError, ValueError, SyntaxError) as error:
        # gdbus が無い・拡張が無いか無効・時間切れ・出力の書式が違う: 読めなかったことを残して空を返す
        logger.warning(f"フォーカスしているウィンドウの wm_class を読めなかった（{error!r}）")
        return ()

    # 3. 空でない文字列をこの順に返す
    return tuple(value for key in WM_CLASS_KEYS if (value := window.get(key)))
