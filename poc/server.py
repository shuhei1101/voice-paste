"""PoC: ブラウザの録音の受け取り・tailscale serve を通った要求のヘッダーの記録・大きな multipart の受け取り。"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

OUT_DIR: Path = Path(__file__).parent / "out"
"""録れた音声・ヘッダーの記録の置き場所。"""

HEADERS_LOG: Path = OUT_DIR / "headers.jsonl"
"""中継先に届いた要求のヘッダーを 1 行 1 要求で残すファイル。"""

RECORDED_HEADERS: tuple[str, ...] = ("host", "origin", "x-forwarded-host", "x-forwarded-for", "x-forwarded-proto", "sec-fetch-site")
"""記録するヘッダー。"""

RECORD_SECONDS: int = 11
"""偽のマイクから録る秒数（読み上げの 10 秒に余白を足す）。"""

COPY_CHUNK_BYTES: int = 1024 * 1024
"""受けた本文を一時ファイルへ写すときの 1 回の大きさ。"""

logger = logging.getLogger(__name__)
app = FastAPI()

RECORD_PAGE = """<!doctype html><meta charset="utf-8"><title>record</title><pre id="log"></pre>
<script>
const log = (s) => { document.getElementById("log").textContent += s + "\\n"; };
const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/ogg;codecs=opus"];
async function recordOne(stream, mime) {
  const rec = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 32000 });
  const chunks = [];
  rec.ondataavailable = (e) => chunks.push(e.data);
  const done = new Promise((r) => (rec.onstop = r));
  let startedAt = 0;
  rec.onstart = () => (startedAt = performance.now());
  rec.start(1000);
  await new Promise((r) => setTimeout(r, __SECONDS__ * 1000));
  rec.stop();
  await done;
  const elapsedMs = performance.now() - startedAt;
  const blob = new Blob(chunks, { type: rec.mimeType });
  const name = "edge_" + mime.replace(/[^a-z0-9]+/gi, "_");
  await fetch("/save?name=" + encodeURIComponent(name) + "&mime=" + encodeURIComponent(rec.mimeType), { method: "POST", body: blob });
  await fetch("/save?name=" + encodeURIComponent(name + ".json"), { method: "POST", body: JSON.stringify({ mime: rec.mimeType, size: blob.size, elapsed_ms: elapsedMs }) });
  log("saved " + name + " " + blob.size + " " + rec.mimeType);
}
(async () => {
  const mime = new URLSearchParams(location.search).get("mime");
  const support = Object.fromEntries(types.map((t) => [t, MediaRecorder.isTypeSupported(t)]));
  await fetch("/save?name=support.json", { method: "POST", body: JSON.stringify({ ua: navigator.userAgent, support }) });
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  await recordOne(stream, mime);
  await fetch("/save?name=done.txt", { method: "POST", body: "done" });
})();
</script>"""

PROBE_PAGE = """<!doctype html><meta charset="utf-8"><title>probe</title><pre id="log"></pre>
<script>
(async () => {
  await fetch("probe/get");
  const form = new FormData();
  form.append("audio", new Blob(["x"], { type: "audio/webm" }), "a.webm");
  await fetch("probe/post", { method: "POST", body: form });
  await fetch("probe/get_done");
  document.getElementById("log").textContent = "done";
})();
</script>"""


def _record_headers(label: str, request: Request) -> None:
    """要求のヘッダーのうち記録するものを 1 行の JSON で残す。"""
    row = {"label": label, "method": request.method, "path": request.url.path}
    row.update({name: request.headers.get(name) for name in RECORDED_HEADERS})
    with HEADERS_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


@app.get("/record")
def record_page() -> HTMLResponse:
    """偽のマイクから MediaRecorder で録って送り返すページを返す。"""
    return HTMLResponse(RECORD_PAGE.replace("__SECONDS__", str(RECORD_SECONDS)))


@app.post("/save")
async def save(request: Request, name: str) -> JSONResponse:
    """ページが送った本文をそのまま out へ書く。"""
    body = await request.body()
    (OUT_DIR / Path(name).name).write_bytes(body)
    return JSONResponse({"size": len(body)})


@app.get("/probe")
def probe_page(request: Request) -> HTMLResponse:
    """同一オリジンの GET と POST を 1 回ずつ送るページを返す。"""
    _record_headers("page", request)
    return HTMLResponse(PROBE_PAGE)


@app.get("/probe/get")
@app.get("/probe/get_done")
def probe_get(request: Request) -> JSONResponse:
    """GET に付いたヘッダーを記録する。"""
    _record_headers("fetch_get", request)
    return JSONResponse({"ok": True})


@app.post("/probe/post")
def probe_post(request: Request) -> JSONResponse:
    """POST に付いたヘッダーを記録する。"""
    _record_headers("fetch_post", request)
    return JSONResponse({"ok": True})


@app.post("/upload", status_code=202)
def upload(audio: UploadFile) -> JSONResponse:
    """multipart の audio を一時ファイルへ写し、写した大きさと秒数を返す。"""
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(delete=False, dir=OUT_DIR, suffix=".upload") as temp:
        shutil.copyfileobj(audio.file, temp, COPY_CHUNK_BYTES)
        written = temp.tell()
    return JSONResponse(
        {"size": written, "copy_sec": round(time.perf_counter() - started, 3)}, status_code=202
    )


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]))
