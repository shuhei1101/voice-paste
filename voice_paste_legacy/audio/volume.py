"""Windows システム音量の取得・設定・フェード制御モジュール。"""

import threading
import time

from voice_paste_legacy.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_fade_stop_event: threading.Event = threading.Event()
_fade_thread: threading.Thread | None = None


def _get_endpoint_volume():
    """EndpointVolume COM インターフェースを返す。失敗時は None。

    pycaw 20251023 以降は AudioDevice.EndpointVolume を直接使用する。
    スレッドから呼ぶ前に CoInitialize 済みであること。
    """
    try:
        from pycaw.pycaw import AudioUtilities
        dev = AudioUtilities.GetSpeakers()
        return dev.EndpointVolume
    except Exception:
        return None


def get_master_volume() -> float:
    """マスター音量を 0.0–100.0 で返す。取得失敗時は -1.0。"""
    import comtypes
    comtypes.CoInitialize()
    try:
        iface = _get_endpoint_volume()
        if iface is None:
            return -1.0
        return iface.GetMasterVolumeLevelScalar() * 100.0
    except Exception:
        return -1.0
    finally:
        comtypes.CoUninitialize()


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
        import comtypes
        comtypes.CoInitialize()
        try:
            iface = _get_endpoint_volume()
            if iface is None:
                return

            current = iface.GetMasterVolumeLevelScalar() * 100.0

            if abs(current - target_pct) < 0.5 or steps <= 0 or duration <= 0:
                iface.SetMasterVolumeLevelScalar(
                    max(0.0, min(100.0, target_pct)) / 100.0, None)
                return

            step_delay = duration / steps
            delta = (target_pct - current) / steps

            for i in range(1, steps + 1):
                if stop.is_set():
                    return
                level = current + delta * i
                iface.SetMasterVolumeLevelScalar(
                    max(0.0, min(100.0, level)) / 100.0, None)
                if i < steps:
                    time.sleep(step_delay)
        except Exception:
            logger.exception("Volume fade failed.")
        finally:
            comtypes.CoUninitialize()

    with _lock:
        _fade_thread = threading.Thread(target=_worker, daemon=True, name="volume-fade")
        _fade_thread.start()
