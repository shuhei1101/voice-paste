"""OpenAI API の文字起こしの代わりに、127.0.0.1 で待ち受けるテスト用のエンドポイント。実際の OpenAI API へは送信しない（従量課金のため）。"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOOPBACK = "127.0.0.1"
API_KEY = "sk-voice-paste-e2e-test-key"
"""テストが常駐アプリへ渡す API キー（テスト用の文字列。ログに書かれないことを確かめる）。"""

TRANSCRIPTIONS_PATH = "/v1/audio/transcriptions"
"""ベース URL（`{エンドポイントの URL}/v1`）の後ろにつながる、文字起こしのパス。"""

UNAUTHORIZED_BODY = {"error": {"type": "invalid_request_error", "code": "invalid_api_key"}}
"""API キーの誤り（401）で OpenAI API が返す本文。"""


@dataclass(frozen=True)
class RecordedRequest:
    """エンドポイントが受けた要求 1 件。"""

    path: str
    headers: dict[str, str]
    """要求のヘッダー（小文字の名前）。"""
    body: bytes

    def form_parts(self) -> list[tuple[str, bytes]]:
        """multipart の本文を、届いた順の（欄の名前, 値）に分けて返す（同じ名前の欄は繰り返し並ぶ。file は音声のバイト列）。"""
        boundary = self.headers["content-type"].split("boundary=")[1].encode()
        parts: list[tuple[str, bytes]] = []
        for part in self.body.split(b"--" + boundary):
            head, separator, value = part.partition(b"\r\n\r\n")
            name = re.search(rb'name="([^"]+)"', head)
            if separator and name is not None:
                parts.append((name.group(1).decode(), value.removesuffix(b"\r\n")))
        return parts

    def form_fields(self) -> dict[str, bytes]:
        """multipart の本文を、欄の名前 → 値（file は音声のバイト列）に分けて返す。"""
        return dict(self.form_parts())


class FakeOpenAIEndpoint:
    """受けた文字起こしの要求を覚え、決めたステータスと本文を返すエンドポイント。"""

    def __init__(self, *, status: int = 200, text: str = "") -> None:
        self.status = status
        """返すステータス。"""
        self.text = text
        """ステータスが 200 のときに返す、起こした文字。"""
        self.error_body: dict[str, object] = UNAUTHORIZED_BODY
        """ステータスが 200 でないときに返す本文。"""
        self.requests: list[RecordedRequest] = []
        self._lock = threading.Lock()
        endpoint = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                with endpoint._lock:
                    endpoint.requests.append(
                        RecordedRequest(
                            path=self.path,
                            headers={key.lower(): value for key, value in self.headers.items()},
                            body=body,
                        )
                    )
                payload = {"text": endpoint.text} if endpoint.status == 200 else endpoint.error_body
                content = json.dumps(payload).encode()
                self.send_response(endpoint.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                """アクセスログを出さない。"""

        self._server = ThreadingHTTPServer((LOOPBACK, 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """設定の `transcription.openai.base_url` に書く URL。"""
        return f"http://{LOOPBACK}:{self._server.server_address[1]}/v1"

    def start(self) -> None:
        """待ち受けを始める。"""
        self._thread.start()

    def stop(self) -> None:
        """待ち受けを止める。"""
        self._server.shutdown()
        self._server.server_close()
