"""Windows システム音量の取得・設定・フェード制御モジュール。"""

import threading
import time

from voice_paste.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_fade_stop_event: threading.Event = threading.Event()
_fade_thread: threading.Thread | None = None


def _get_interface():
    """IAudioEndpointVolume COM インターフェースを返す。失敗時は None。"""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


def get_master_volume() -> float:
    """マスター音量を 0.0–100.0 で返す。取得失敗時は -1.0。"""
    iface = _get_interface()
    if iface is None:
        return -1.0
    try:
        return iface.GetMasterVolumeLevelScalar() * 100.0
    except Exception:
        return -1.0


def set_master_volume(level: float) -> None:
    """マスター音量を 0.0–100.0 で設定する。"""
    iface = _get_interface()
    if iface is None:
        return
    try:
        iface.SetMasterVolumeLevelScalar(max(0.0, min(100.0, level)) / 100.0, None)
    except Exception:
        pass


def fade_volume(target_pct: float, duration: float, steps: int = 30) -> None:
    """現在の音量から target_pct まで duration 秒かけてフェードする（バックグラウンド）。

    既存のフェードが進行中の場合はキャンセルして新しいフェードを開始する。
    """
    global _fade_thread, _fade_stop_event

    with _lock:
        _fade_stop_event.set()
        if _fade_thread and _fade_thread.is_alive():
            _fade_thread.join(timeout=1.0)

        _fade_stop_event = threading.Event()
        stop = _fade_stop_event

    def _worker() -> None:
        iface = _get_interface()
        if iface is None:
            return

        try:
            current = iface.GetMasterVolumeLevelScalar() * 100.0
        except Exception:
            return

        if abs(current - target_pct) < 0.5 or steps <= 0 or duration <= 0:
            set_master_volume(target_pct)
            return

        step_delay = duration / steps
        delta = (target_pct - current) / steps

        for i in range(1, steps + 1):
            if stop.is_set():
                return
            level = current + delta * i
            try:
                iface.SetMasterVolumeLevelScalar(max(0.0, min(100.0, level)) / 100.0, None)
            except Exception:
                return
            if i < steps:
                time.sleep(step_delay)

    with _lock:
        _fade_thread = threading.Thread(target=_worker, daemon=True, name="volume-fade")
        _fade_thread.start()
