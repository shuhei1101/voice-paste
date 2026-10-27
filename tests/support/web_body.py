"""`POST /web/transcriptions` に送信する、大きさを指定した multipart の本文を作る補助。

音声の後ろに 0 のバイトを追加して、本文（multipart の境界とヘッダーを含む）をちょうど指定の大きさにする。
後ろに追加した分は、音声の読み取り（形式の確認）に影響しない。
"""

from __future__ import annotations

from collections.abc import Iterator

BOUNDARY = "voice-paste-sized-body-boundary"
"""本文の multipart の境界。"""

CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"
"""本文を送信するときの Content-Type。"""

CHUNK_BYTES = 1_000_000
"""chunked で送信するときの 1 回の大きさ（バイト）。"""


def sized_multipart_body(audio: bytes, total_bytes: int, filename: str = "recording.webm") -> bytes:
    """audio の後ろに 0 のバイトを追加して、本文全体がちょうど total_bytes バイトの multipart の本文にして返す。"""
    head = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
        "Content-Type: audio/webm\r\n\r\n"
    ).encode()
    tail = f"\r\n--{BOUNDARY}--\r\n".encode()
    padding = total_bytes - len(head) - len(tail) - len(audio)
    # 音声と枠だけで指定の大きさを超えるときは、作れない
    if padding < 0:
        raise ValueError(f"音声が大きすぎて {total_bytes} バイトの本文を作れない")
    return head + audio + bytes(padding) + tail


def chunks_of(body: bytes) -> Iterator[bytes]:
    """本文を CHUNK_BYTES ずつに分けて返す（Content-Length を付けずに chunked で送信するため）。"""
    for start in range(0, len(body), CHUNK_BYTES):
        yield body[start : start + CHUNK_BYTES]
