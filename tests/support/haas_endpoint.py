"""Haas の文字起こしのサーバーと wsl.exe の代わり。127.0.0.1 で待ち受けるテスト用のエンドポイント。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import MagicMock

from tests.support.openai_endpoint import LOOPBACK, RecordedRequest

MODEL_NAME = "third-intelligence/Haas-ja-v1.0"


class FakeHaasEndpoint:
    """/health に応答し、受けた文字起こしの要求を覚え、決めたステータスと本文を返すエンドポイント。"""

    def __init__(self, *, port: int = 0, status: int = 200, text: str = "") -> None:
        self.status = status
        """POST /transcriptions が返すステータス。"""
        self.text = text
        """ステータスが 200 のときに返す、起こした文字。"""
        self.detail = ""
        """ステータスが 200 でないときに返す detail。"""
        self.requests: list[RecordedRequest] = []
        self.shutdown_count = 0
        self._started = False
        self._lock = threading.Lock()
        endpoint = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._respond(200, {"ok": True, "model": MODEL_NAME})

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path == "/shutdown":
                    with endpoint._lock:
                        endpoint.shutdown_count += 1
                    self._respond(202, {})
                    return
                with endpoint._lock:
                    endpoint.requests.append(
                        RecordedRequest(
                            path=self.path,
                            headers={key.lower(): value for key, value in self.headers.items()},
                            body=body,
                        )
                    )
                if endpoint.status == 200:
                    self._respond(200, {"text": endpoint.text})
                else:
                    self._respond(endpoint.status, {"detail": endpoint.detail})

            def _respond(self, status: int, payload: dict[str, Any]) -> None:
                content = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                """アクセスログを出さない。"""

        self._server = ThreadingHTTPServer((LOOPBACK, port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        """設定の `transcription.haas.port` に書くポート。"""
        return int(self._server.server_address[1])

    def start(self) -> None:
        """待ち受けを始める。"""
        self._started = True
        self._thread.start()

    def stop(self) -> None:
        """待ち受けを止める。"""
        if self._started:
            self._server.shutdown()
        self._server.server_close()


class FakeWsl:
    """wsl.exe の代わり。起動された引数を記録し、endpoint があれば待ち受けを始める。endpoint が無ければ何も立てない。"""

    def __init__(self, endpoint: FakeHaasEndpoint | None = None) -> None:
        self.endpoint = endpoint
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_kwargs: object) -> MagicMock:
        """サーバーの起動の代わりに、記録して待ち受けを始める。"""
        self.calls.append(args)
        if self.endpoint is not None:
            self.endpoint.start()
        process = MagicMock()
        process.poll.return_value = None
        return process
