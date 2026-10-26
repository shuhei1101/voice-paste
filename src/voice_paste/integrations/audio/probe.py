"""受けた音声を PyAV で開き、容れ物の形式・秒数・大きさを読む。"""

from __future__ import annotations

from typing import BinaryIO

import av
from av.error import FFmpegError

from voice_paste.shared.errors import AudioUnreadableError
from voice_paste.shared.types import AudioProbe

CONTAINER_SUFFIXES: dict[str, str] = {
    "matroska,webm": ".webm",
    "mov,mp4,m4a,3gp,3g2,mj2": ".mp4",
    "ogg": ".ogg",
    "mp3": ".mp3",
    "wav": ".wav",
}
"""PyAV の容れ物の形式の名前 → 一時のファイルと履歴に付ける拡張子。"""

UNKNOWN_SUFFIX: str = ".bin"
"""表に無い形式に付ける拡張子。"""


def _duration_from_packets(
    container: av.container.InputContainer, stream: av.audio.stream.AudioStream
) -> float | None:
    """音声のパケット（デコードしない）の終わりの時刻の最大を秒数にする。求まらなければ None を返す。"""
    latest = 0.0
    for packet in container.demux(stream):
        # 時刻と長さを持つパケットだけが終わりの時刻を表す
        if packet.pts is None or packet.duration is None or packet.time_base is None:
            continue
        latest = max(latest, float((packet.pts + packet.duration) * packet.time_base))
    return latest if latest > 0 else None


def probe_audio(file: BinaryIO) -> AudioProbe:
    """受けた音声を PyAV で開き、容れ物の形式・秒数・大きさを返す。開けない・音声のストリームが無いときは AudioUnreadableError を送出する。"""
    # 1. 大きさを数えて頭へ戻す
    file.seek(0, 2)
    size_bytes = file.tell()
    file.seek(0)

    # 2. 開いて、音声のストリームがあるかを確かめる
    try:
        # 読む専用で開く（SpooledTemporaryFile は mode が書き込みで、PyAV が書き出しと取り違える）
        with av.open(file, mode="r") as container:
            audio_streams = container.streams.audio
            if not audio_streams:
                raise AudioUnreadableError("音声のストリームが無い")

            # 3. 容れ物の形式の名前から拡張子を決める
            container_name = container.format.name
            suffix = CONTAINER_SUFFIXES.get(container_name, UNKNOWN_SUFFIX)

            # 4. 秒数を求める（容れ物が持たなければ、音声のパケットから求める）
            if container.duration is not None:
                duration_sec: float | None = container.duration / av.time_base
            else:
                duration_sec = _duration_from_packets(container, audio_streams[0])
    except FFmpegError as error:
        # PyAV が開けない: 音声の中身は理由に含めない
        raise AudioUnreadableError("音声として読めない") from error

    # 5. 頭へ戻して返す
    file.seek(0)
    return AudioProbe(
        container=container_name,
        suffix=suffix,
        duration_sec=duration_sec,
        size_bytes=size_bytes,
    )
