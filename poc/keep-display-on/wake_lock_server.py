"""wake_lock.html を 127.0.0.1 で配信し、画面からの報告ごとに SystemExecutionState を記録する。

使い方: python wake_lock_server.py {port}
"""

import http.server
import sys
import urllib.parse
from pathlib import Path

from windows_inhibit import display_required

HTML = (Path(__file__).parent / "wake_lock.html").read_bytes()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        if url.path == "/log":
            query = dict(urllib.parse.parse_qsl(url.query))
            print({**query, "display_required": display_required()}, flush=True)
            if query.get("event") in ("released", "error"):
                self.server.done = True  # type: ignore[attr-defined]
            body = b"ok"
        else:
            body = HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    server = http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler)
    server.done = False  # type: ignore[attr-defined]
    print(f"before: display_required={display_required()}", flush=True)
    while not server.done:  # type: ignore[attr-defined]
        server.handle_request()
    print(f"after: display_required={display_required()}", flush=True)


if __name__ == "__main__":
    main()
