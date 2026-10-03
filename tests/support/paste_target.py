"""実機の E2E の貼り付け先。入力欄 1 つの窓を出し、中身と Enter の回数を一定の間隔でファイルへ書き出す。

使い方: `python paste_target.py {状態のファイル} {窓の題}`。
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path

WRITE_INTERVAL_MS = 100
"""状態のファイルへ書き出す間隔。"""

WINDOW_GEOMETRY = "520x110+120+120"
"""窓の大きさと位置。"""


def main(state_file: Path, title: str) -> None:
    """入力欄の窓を出し、中身と Enter の回数を書き出し続ける。"""
    root = tk.Tk()
    root.title(title)
    root.geometry(WINDOW_GEOMETRY)
    entry = tk.Entry(root, font=("Segoe UI", 14))
    entry.pack(fill="x", padx=12, pady=28)
    entry.focus_force()
    enters = {"count": 0}

    def on_return(_event: object) -> str:
        """Enter を数える（入力欄には何も入れない）。"""
        enters["count"] += 1
        return "break"

    def dump() -> None:
        """入力欄の中身と Enter の回数を書き出す。"""
        state = {"text": entry.get(), "enters": enters["count"]}
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        root.after(WRITE_INTERVAL_MS, dump)

    entry.bind("<Return>", on_return)
    dump()
    root.mainloop()


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
