"""pycaw で既定の再生デバイスのマスター音量を下げ・戻す。pycaw の API に触れるのはこのファイルだけ。"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import comtypes

from voice_paste.shared.errors import VolumeControlError

if TYPE_CHECKING:
    from pycaw.pycaw import IAudioEndpointVolume

logger = logging.getLogger(__name__)

FADE_STEPS: int = 30
"""音量を変えるときに分けるステップの数。"""

FADE_JOIN_TIMEOUT_SEC: float = 1.0
"""進行中のフェードを打ち切るときに、そのスレッドの終わりを待つ上限（秒）。"""

SINGLE_WRITE_MAX_DELTA: float = 0.005
"""今の音量と目標の差がこれ未満なら、ステップに分けず 1 回で書く。"""

# 音量の読み書きとフェードの状態を守るロック
_volume_lock = threading.Lock()
# 進行中のフェードのスレッド・打ち切りの合図・目標の音量（_cancel_fade と _fade_to だけが触る）
_fade_thread: threading.Thread | None = None
_fade_stop: threading.Event = threading.Event()
_fade_target: float | None = None


def lower_volume(ratio: float, fade_sec: float) -> float:
    """今のマスター音量に ratio を掛けた音量へ fade_sec をかけて下げ始め、下げる前の音量を返す。"""
    with _volume_lock:
        # 1. 進行中のフェードを打ち切る
        cancelled_target = _cancel_fade()

        # 2. 下げる前の音量を決める。戻している途中なら、戻しの目標の音量にする
        if cancelled_target is not None:
            volume_before = cancelled_target
        else:
            volume_before = _read_master_volume()

        # 3. 割合を掛けた音量へ変える
        _fade_to(_clamp(volume_before * ratio), fade_sec)
        return volume_before


def restore_volume(volume: float, fade_sec: float) -> None:
    """マスター音量を volume へ fade_sec をかけて戻し始める。"""
    with _volume_lock:
        # 下げている途中のフェードも打ち切ってから、戻す音量へ変える
        _cancel_fade()
        _fade_to(_clamp(volume), fade_sec)


def _clamp(volume: float) -> float:
    """音量を 0.0〜1.0 に収める。"""
    return min(1.0, max(0.0, volume))


def _open_endpoint_volume() -> IAudioEndpointVolume:
    """既定の再生デバイスの音量のインターフェースを返す。呼ぶスレッドで COM を初期化しておく。"""
    # pycaw はバージョンで API が変わるため、読み込みの失敗も呼び出し側で VolumeControlError にできるよう関数の中で読む
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


def _read_master_volume() -> float:
    """COM を初期化して、マスター音量（0.0〜1.0）を読む。読めなければ VolumeControlError を送出する。"""
    try:
        comtypes.CoInitialize()
        try:
            return float(_open_endpoint_volume().GetMasterVolumeLevelScalar())
        finally:
            comtypes.CoUninitialize()
    except Exception as error:  # noqa: BLE001 pycaw・COM が送出する例外の型はバージョンで変わる
        raise VolumeControlError(f"音量を読めませんでした: {error}") from error


def _write_master_volume(volume: float) -> None:
    """COM を初期化して、マスター音量を書く。書けなければ VolumeControlError を送出する。"""
    try:
        comtypes.CoInitialize()
        try:
            _open_endpoint_volume().SetMasterVolumeLevelScalar(volume, None)
        finally:
            comtypes.CoUninitialize()
    except Exception as error:  # noqa: BLE001 pycaw・COM が送出する例外の型はバージョンで変わる
        raise VolumeControlError(f"音量を書けませんでした: {error}") from error


def _fade_to(target: float, fade_sec: float) -> None:
    """target へ fade_sec をかけて変える。fade_sec が 0 以下なら呼び出しの中ですぐ変える。"""
    global _fade_thread, _fade_stop, _fade_target

    # 1. すぐ変える: 呼び出しの中で書く
    if fade_sec <= 0:
        _write_master_volume(target)
        return

    # 2. 時間をかけて変える: 別のスレッドで進め、呼び出し元を待たせない
    _fade_target = target
    _fade_stop = threading.Event()
    _fade_thread = threading.Thread(
        target=_run_fade, args=(target, fade_sec, _fade_stop), daemon=True, name="volume-fade"
    )
    _fade_thread.start()


def _run_fade(target: float, fade_sec: float, stop: threading.Event) -> None:
    """フェードのスレッドの本体。今の音量から target までを FADE_STEPS ステップに分けて書く。"""
    comtypes.CoInitialize()
    try:
        endpoint = _open_endpoint_volume()
        current = float(endpoint.GetMasterVolumeLevelScalar())

        # 差が小さければステップに分けず 1 回で書く
        if abs(current - target) < SINGLE_WRITE_MAX_DELTA:
            endpoint.SetMasterVolumeLevelScalar(target, None)
            return

        step_sec = fade_sec / FADE_STEPS
        for step in range(1, FADE_STEPS + 1):
            # 打ち切りを知らされたら、次のステップを書かずに終わる
            if stop.is_set():
                return
            # 最後のステップは目標そのものを書き、丸めの誤差を残さない
            if step == FADE_STEPS:
                endpoint.SetMasterVolumeLevelScalar(target, None)
                return
            endpoint.SetMasterVolumeLevelScalar(
                current + (target - current) * step / FADE_STEPS, None
            )
            # 次のステップまで待つ（打ち切られたらすぐ起きる）
            stop.wait(step_sec)
    except Exception as error:  # noqa: BLE001 スレッドの最上位。pycaw・COM が送出する例外の型はバージョンで変わる
        logger.exception(f"音量を変えられなかった（{error}）")
    finally:
        comtypes.CoUninitialize()


def _cancel_fade() -> float | None:
    """進行中のフェードに打ち切りを知らせて終わりを待ち、そのフェードの目標の音量を返す。"""
    global _fade_target

    # 進行中のフェードが無ければ何もしない
    thread = _fade_thread
    if thread is None or not thread.is_alive():
        _fade_target = None
        return None

    # 打ち切りを知らせ、スレッドの終わりを待つ
    _fade_stop.set()
    thread.join(FADE_JOIN_TIMEOUT_SEC)
    target = _fade_target
    _fade_target = None
    return target
