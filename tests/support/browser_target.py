"""実機の E2E の、ブラウザ添付のプリセットの開き先。

127.0.0.1 で入力欄 1 つの画面を配り、画面の入力欄の中身と Enter の回数を、画面から受けて覚える（Edge のアプリのウィンドウで開かれる前提）。
外のサイトへは行かない。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import win32con
import win32gui

LOOPBACK = "127.0.0.1"
BROWSER_TARGET_TITLE = "voice-paste E2E browser target"
"""開き先の画面の題（アプリのウィンドウの題になる）。"""

REPORT_INTERVAL_MS = 100
"""画面が入力欄の状態を送る間隔。"""

PAGE = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{BROWSER_TARGET_TITLE}</title>
</head>
<body>
<input id="box" type="text" autofocus style="width: 90%; font-size: 20px; margin: 24px;">
<script>
  const box = document.getElementById("box");
  let enters = 0;
  box.focus();
  window.addEventListener("focus", () => box.focus());
  box.addEventListener("keydown", (event) => {{
    if (event.key === "Enter") {{
      enters += 1;
      event.preventDefault();
    }}
  }});
  setInterval(() => {{
    fetch("/state", {{
      method: "POST",
      body: JSON.stringify({{text: box.value, enters: enters}}),
    }});
  }}, {REPORT_INTERVAL_MS});
</script>
</body>
</html>
"""
"""配る画面。入力欄にフォーカスを置き、Enter を数えて、状態を /state へ送り続ける。"""


class BrowserTarget:
    """ブラウザ添付のプリセットの開き先。画面を配り、画面が送ってくる入力欄の状態を覚える。"""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {"text": "", "enters": 0}
        self.page_requests = 0
        """画面（/）を配った回数。"""
        target = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = PAGE.encode("utf-8")
                target.page_requests += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                target._state = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(204)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                """アクセスログを出さない。"""

        self._server = ThreadingHTTPServer((LOOPBACK, 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """プリセットの URL に書く、画面の URL。"""
        return f"http://{LOOPBACK}:{self._server.server_address[1]}/"

    def start(self) -> None:
        """待ち受けを始める。"""
        self._thread.start()

    def stop(self) -> None:
        """待ち受けを止める。"""
        self._server.shutdown()
        self._server.server_close()

    def text(self) -> str:
        """画面の入力欄の中身。"""
        return str(self._state["text"])

    def enters(self) -> int:
        """画面の入力欄で受けた Enter の回数。"""
        return int(self._state["enters"])

    @staticmethod
    def _windows() -> list[int]:
        """開き先の画面の題を持つ窓のハンドルを返す。"""
        found: list[int] = []

        def _collect(handle: int, _extra: object) -> None:
            if win32gui.IsWindowVisible(handle) and BROWSER_TARGET_TITLE in win32gui.GetWindowText(handle):
                found.append(handle)

        win32gui.EnumWindows(_collect, None)
        return found

    def window_open(self) -> bool:
        """開き先の画面が窓として開いているか。"""
        return bool(self._windows())

    def close_window(self) -> None:
        """開いた窓を閉じる。"""
        for handle in self._windows():
            win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
