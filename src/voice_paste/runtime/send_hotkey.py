"""GNOME のカスタムショートカットが流すコマンド。押されたホットキーを常駐サービスの終了の依頼のソケットへ送信する。

`python -m voice_paste.runtime.send_hotkey {排他の名前} {ホットキー}` で起動する。
"""

from __future__ import annotations

import socket
import sys

from voice_paste.runtime.single_instance_linux import HOTKEY_REQUEST_PREFIX, _quit_socket_name

EXIT_OK: int = 0
"""送信できた、または常駐サービスが動いていないときの終了コード。"""

EXIT_USAGE: int = 2
"""引数の数が違うときの終了コード。"""

EXPECTED_ARGS: int = 2
"""引数の数（排他の名前・ホットキー）。"""


def main(argv: list[str] | None = None) -> int:
    """押されたホットキーを常駐サービスへ送信する。常駐サービスが動いていない（接続できない）ときは何もせず 0 で終わる。"""
    args = sys.argv[1:] if argv is None else argv

    # 1. 引数が排他の名前・ホットキーの 2 つか
    if len(args) != EXPECTED_ARGS:
        # 違う: 使い方の誤りとして終わる
        return EXIT_USAGE
    name, hotkey = args

    # 2. 終了の依頼のソケットへ接続して、ホットキーを送信する
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(_quit_socket_name(name))
            client.sendall(HOTKEY_REQUEST_PREFIX + hotkey.encode("utf-8"))
    except OSError:
        # 常駐サービスが動いていない: 登録が残ったままでも、押すたびにエラーを出さない
        return EXIT_OK
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
