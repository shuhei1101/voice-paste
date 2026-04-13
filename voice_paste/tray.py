"""システムトレイアイコン管理モジュール（pystray ベース）。"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Literal

from PIL import Image, ImageDraw, ImageFont
import pystray

from voice_paste.constants import DEFAULT_ICON_FILE, LOG_DIR
from voice_paste.logger import get_logger

logger = get_logger(__name__)

# トレイアイコンのデフォルトサイズ
_ICON_SIZE = 64

# トレイアイコンの状態
TrayState = Literal["idle", "recording", "transcribing"]

# 状態ごとのマイク本体色
_STATE_COLORS: dict[TrayState, tuple[int, int, int, int]] = {
    "idle": (0, 120, 212, 255),         # 青
    "recording": (220, 40, 40, 255),    # 赤
    "transcribing": (16, 124, 16, 255), # 緑
}


def _generate_mic_icon(state: TrayState = "idle") -> Image.Image:
    """マイク+T のトレイアイコンを状態ごとの色で生成する。"""
    s = _ICON_SIZE
    mic_color = _STATE_COLORS[state]
    text_color = (255, 255, 255, 255)
    part_color = (200, 200, 200, 255)

    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # マイク本体
    mx, my = s // 2, s // 2 - 5
    mw, mh = 13, 20
    draw.rounded_rectangle(
        (mx - mw, my - mh, mx + mw, my + mh),
        radius=mw, fill=mic_color,
    )

    # 「T」
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "T", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((mx - tw // 2, my - th // 2 - 3), "T", fill=text_color, font=font)

    # アーチ
    arc_w = 18
    draw.arc(
        (mx - arc_w, my - 8, mx + arc_w, my + mh + 10),
        start=0, end=180, fill=part_color, width=2,
    )

    # スタンド
    draw.rectangle((mx - 1, my + mh + 5, mx + 1, my + mh + 15), fill=part_color)

    # 台座
    draw.rectangle((mx - 8, my + mh + 13, mx + 8, my + mh + 16), fill=part_color)

    return image


_STATE_TITLES: dict[TrayState, str] = {
    "idle": "voice-paste: 待機中",
    "recording": "voice-paste: 録音中",
    "transcribing": "voice-paste: 文字起こし中",
}


def update_tray_state(icon: pystray.Icon, state: TrayState) -> None:
    """トレイアイコンの状態を更新する。"""
    icon.icon = _generate_mic_icon(state)
    icon.title = _STATE_TITLES[state]
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
    return _generate_mic_icon("idle")


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
    tooltip = _STATE_TITLES["idle"]

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
