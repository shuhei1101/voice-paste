"""PoC の相手のウィンドウ。貼り付け先（入力欄の中身をファイルへ書く）か、ほかの最前面のウィンドウになる。"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit

# 最前面を取り直す間隔（--fight のとき）
FIGHT_INTERVAL_MS = 100
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
ctypes.windll.user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
]


def main() -> int:
    """引数のとおりにウィンドウを出し、閉じられるまで動かす。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--topmost", action="store_true")
    parser.add_argument("--fight", action="store_true")
    parser.add_argument("--geometry", default="200,200,480,240")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    edit = QPlainTextEdit()
    edit.setWindowTitle(args.title)
    x, y, w, h = (int(v) for v in args.geometry.split(","))
    edit.setGeometry(x, y, w, h)
    # 最前面の相手にするときだけ最前面の指定を付ける
    if args.topmost:
        edit.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # 貼り付け先にするときは、入力欄の中身が変わるたびにファイルへ書く
    if args.out is not None:
        out: Path = args.out
        edit.textChanged.connect(lambda: out.write_text(edit.toPlainText(), encoding="utf-8"))
    edit.show()

    # 取り合う相手にするときは、一定の間隔で最前面を取り直す
    if args.fight:
        timer = QTimer()
        hwnd = int(edit.winId())
        timer.timeout.connect(
            lambda: ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )
        )
        timer.start(FIGHT_INTERVAL_MS)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())