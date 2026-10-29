"""GNOME のカスタムショートカットから起動し、押されたホットキーを常駐サービスの終了の依頼のソケットへ送信する。

常駐サービスが動いていなければ（接続できなければ）何もせず 0 で終わる。
"""

from __future__ import annotations

import socket
import sys

from voice_paste.runtime.single_instance_linux import HOTKEY_REQUEST_PREFIX

EXPECTED_ARGC: int = 3
"""引数の数（プログラム名・排他の名前・ホットキー）。"""


def main() -> int:
    """引数の排他の名前のソケットへ、押されたホットキーを送信する。"""
    if len(sys.argv) != EXPECTED_ARGC:
        return 2
    name, hotkey = sys.argv[1], sys.argv[2]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(f"\0{name}-quit")
            client.sendall(HOTKEY_REQUEST_PREFIX + hotkey.encode("utf-8"))
    except OSError:
        # 常駐サービスが動いていない: 何もしない
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
