"""システムトレイアイコン管理モジュール（pystray ベース）。"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Literal

from PIL import Image, ImageDraw
import pystray

from voice_paste.constants import DEFAULT_ICON_FILE, LOG_DIR
from voice_paste.logger import get_logger

logger = get_logger(__name__)

# トレイアイコンのデフォルトサイズ
_ICON_SIZE = 64

# トレイアイコンの状態
TrayState = Literal["idle", "recording", "transcribing"]

# 状態ごとの色: (fill, outline)
_STATE_COLORS: dict[TrayState, tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] = {
    "idle": ((255, 255, 255, 255), (180, 180, 180, 255)),         # 白丸
    "recording": ((220, 40, 40, 255), (255, 255, 255, 255)),      # 赤丸
    "transcribing": ((0, 120, 212, 255), (255, 255, 255, 255)),   # 青丸
}


def _generate_circle_icon(state: TrayState = "idle") -> Image.Image:
    """指定された状態の丸アイコンを動的生成する。"""
    fill, outline = _STATE_COLORS[state]
    image = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 6
    draw.ellipse(
        (margin, margin, _ICON_SIZE - margin, _ICON_SIZE - margin),
        fill=fill,
        outline=outline,
        width=3,
    )
    return image


def update_tray_state(icon: pystray.Icon, state: TrayState) -> None:
    """トレイアイコンの状態を更新する。"""
    icon.icon = _generate_circle_icon(state)
    logger.debug("Tray icon state changed to: %s", state)


def _load_icon_image(icon_path: Path) -> Image.Image:
    """トレイアイコン画像をロードする（無ければ動的生成）。"""
    if icon_path.exists():
        try:
            logger.info("Loading tray icon from: %s", icon_path)
            return Image.open(icon_path).convert("RGBA")
        except Exception:
            logger.exception("Failed to load icon file, falling back to generated icon.")
    logger.info("Icon file not found, generating default icon.")
    return _generate_circle_icon("idle")


def _open_log_folder() -> None:
    """エクスプローラーでログフォルダを開く。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Opening log folder: %s", LOG_DIR)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(LOG_DIR))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(LOG_DIR)])
    except Exception:
        logger.exception("Failed to open log folder.")


def build_tray_icon(
    hotkey: str,
    on_start_session: Callable[[], None],
    on_settings: Callable[[], None],
    on_quit: Callable[[], None],
) -> pystray.Icon:
    """
    トレイアイコンを構築する。

    :param hotkey: 表示用のホットキー文字列
    :param on_start_session: 録音開始要求時に呼ぶコールバック
    :param on_quit: 終了要求時に呼ぶコールバック
    :return: 構築済み pystray.Icon インスタンス（未起動）
    """
    image = _load_icon_image(DEFAULT_ICON_FILE)
    tooltip = f"voice-paste (hotkey: {hotkey})"

    def _on_start(icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        logger.info("Tray menu: start session requested.")
        on_start_session()

    def _on_open_log(icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        _open_log_folder()

    def _on_settings(icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        logger.info("Tray menu: settings requested.")
        on_settings()

    def _on_quit(icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        logger.info("Tray menu: quit requested.")
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("録音開始", _on_start, default=True),
        pystray.MenuItem("ログフォルダを開く", _on_open_log),
        pystray.MenuItem("設定", _on_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("終了", _on_quit),
    )

    icon = pystray.Icon(
        name="voice_paste",
        icon=image,
        title=tooltip,
        menu=menu,
    )
    return icon
