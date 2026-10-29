"""Linux（Xorg）のアクティブなウィンドウの WM_CLASS の読み取り。python-xlib に触れるのはこのファイルだけ。"""

from __future__ import annotations

import logging

import Xlib.display
import Xlib.error
from Xlib import X

logger = logging.getLogger(__name__)

ACTIVE_WINDOW_PROPERTY: str = "_NET_ACTIVE_WINDOW"
"""ルートウィンドウが持つ、アクティブなウィンドウの ID を指すプロパティの名前。"""


def read_active_wm_class() -> tuple[str, ...]:
    """アクティブなウィンドウの WM_CLASS（インスタンス名, クラス名）を返す。読めないときは空を返し、貼り付けを止めない。"""
    display: Xlib.display.Display | None = None
    try:
        # 1. DISPLAY の X サーバーへつなぎ、ルートウィンドウのアクティブなウィンドウの ID を読む
        display = Xlib.display.Display()
        atom = display.intern_atom(ACTIVE_WINDOW_PROPERTY)
        active = display.screen().root.get_full_property(atom, X.AnyPropertyType)

        # アクティブなウィンドウが無い（プロパティが無い・空）
        if active is None or not active.value:
            return ()

        # 2. そのウィンドウの WM_CLASS を読む（無ければ空）
        window = display.create_resource_object("window", active.value[0])
        wm_class = window.get_wm_class()
        return tuple(wm_class) if wm_class else ()
    except (Xlib.error.DisplayError, Xlib.error.XError, Xlib.error.ConnectionClosedError) as error:
        # つなげない・ウィンドウが消えた・接続が切れた: 読めなかったことを残して空を返す
        logger.warning(f"アクティブなウィンドウの WM_CLASS を読めなかった（{error}）")
        return ()
    finally:
        # つないだ Display は最後に閉じる
        if display is not None:
            display.close()
