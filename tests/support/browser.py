"""外の端末の画面（`GET /web/`）を Windows の Edge で開いて操作・観測する、E2E の補助。

Edge を headless で起動し、DevTools Protocol（WebSocket）で画面を操作する。標準ライブラリだけで話す。
マイクは偽物（`--use-fake-device-for-media-stream`）で、許可の確認は自動で通す（`--use-fake-ui-for-media-stream`）。
偽のマイクに流す音は、`--use-file-for-fake-audio-capture` に渡した WAV（SAPI で書き出した文）。
画面の時計は `Date.now` を差し替えて進められる（録音の上限時間を待たずに確かめる）。
端末の保存（IndexedDB・localStorage）は、画面を開いたオリジンの中を JS で読み書きする。
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
"""Edge の実行ファイル。"""

LAUNCH_TIMEOUT_SEC = 20.0
"""Edge の DevTools に繋がるまで待つ上限。"""

PAGE_TIMEOUT_SEC = 20.0
"""画面の状態が整うまで待つ既定の上限。"""

POLL_SEC = 0.1
"""画面の状態を確かめる間隔。"""

SOCKET_TIMEOUT_SEC = 60.0
"""DevTools の応答を待つ上限。"""

DB_NAME = "voice-paste"
"""画面が端末の音声を残す IndexedDB の名前。"""

DB_STORE = "kept_audio"
"""画面が端末の音声を残す IndexedDB のストアの名前。"""

DB_KEY = "latest"
"""端末の音声の固定のキー。"""

RESULTS_KEY = "voice-paste.results"
"""画面が結果を残す localStorage のキー。"""

LOCAL_HOST = "localhost"
"""画面を開くホスト名（ゲートウェイが渡す Host に合わせる）。"""

PAGE_READY = (
    "document.readyState === 'complete' && !!document.querySelector('[data-element=record_button]')"
)
"""画面を開き終えた（読み込みが終わり、録音開始ボタンが出ている）ことを表す JS の式。"""

CLOCK_SCRIPT = """
(() => {
  let offset = 0;
  const real = Date.now.bind(Date);
  Date.now = () => real() + offset;
  window.__advanceClock = (ms) => { offset += ms; };
})();
"""
"""画面の時計（Date.now）を進められるようにする、新しい文書ごとに先に走らせる JS。"""

OPEN_STORE_JS = f"""
const openStore = (mode) => new Promise((resolve, reject) => {{
  const open = indexedDB.open({json.dumps(DB_NAME)}, 1);
  open.onupgradeneeded = () => open.result.createObjectStore({json.dumps(DB_STORE)});
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {{
    const db = open.result;
    const transaction = db.transaction({json.dumps(DB_STORE)}, mode);
    resolve({{ db, transaction, store: transaction.objectStore({json.dumps(DB_STORE)}) }});
  }};
}});
"""
"""端末内の音声の IndexedDB のストアを開く JS の関数。"""


class DevToolsError(RuntimeError):
    """DevTools の呼び出しが失敗した。"""


class _WebSocket:
    """DevTools に繋ぐ最小の WebSocket クライアント（テキストのメッセージだけ）。"""

    def __init__(self, url: str) -> None:
        host, path = url[len("ws://") :].split("/", 1)
        name, port = host.split(":")
        self._socket = socket.create_connection((name, int(port)), timeout=SOCKET_TIMEOUT_SEC)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self._recv(4096)
        self._buffer = response.split(b"\r\n\r\n", 1)[1]

    def _recv(self, size: int) -> bytes:
        """最大 size バイト受け取る。相手が接続を閉じていたら DevToolsError にする。"""
        data = self._socket.recv(size)
        if not data:
            raise DevToolsError("Edge が DevTools の接続を閉じた")
        return data

    def _read(self, size: int) -> bytes:
        """size バイト読む。"""
        while len(self._buffer) < size:
            self._buffer += self._recv(65536)
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def send(self, message: dict[str, Any]) -> None:
        """メッセージを 1 つ送信する（クライアントからはマスクを付ける）。"""
        data = json.dumps(message).encode()
        mask = os.urandom(4)
        size = len(data)
        if size < 126:
            header = bytes([0x81, 0x80 | size])
        elif size < 65536:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", size)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", size)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self._socket.sendall(header + mask + masked)

    def receive(self) -> dict[str, Any] | None:
        """メッセージを 1 つ読む。テキスト以外は None を返す。"""
        payload = b""
        while True:
            first, second = self._read(2)
            final, opcode = first & 0x80, first & 0x0F
            size = second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8))[0]
            payload += self._read(size)
            if final:
                return json.loads(payload.decode()) if opcode == 1 else None

    def close(self) -> None:
        """接続を閉じる。"""
        self._socket.close()


class BrowserPage:
    """Edge の 1 つのタブ。JS の実行と、画面の要素の操作・観測を持つ。"""

    def __init__(self, websocket_url: str) -> None:
        self._ws = _WebSocket(websocket_url)
        self._next_id = 0
        self.call("Page.enable")
        self.call("Runtime.enable")
        # ヘッドレスでもフォーカスがある体にする（クリップボードの読み書きに要る）
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Page.addScriptToEvaluateOnNewDocument", source=CLOCK_SCRIPT)

    def call(self, method: str, **params: Any) -> dict[str, Any]:  # noqa: ANN401 DevTools の引数
        """DevTools のメソッドを呼び、結果を返す。"""
        self._next_id += 1
        self._ws.send({"id": self._next_id, "method": method, "params": params})
        while True:
            message = self._ws.receive()
            if message is not None and message.get("id") == self._next_id:
                if "error" in message:
                    raise DevToolsError(f"{method}: {message['error']}")
                return dict(message.get("result", {}))

    def evaluate(self, expression: str, *, user_gesture: bool = False) -> Any:  # noqa: ANN401 JS の戻り値
        """JS の式（Promise は待つ）を評価して、値を返す。例外なら DevToolsError にする。"""
        result = self.call(
            "Runtime.evaluate",
            expression=expression,
            awaitPromise=True,
            returnByValue=True,
            userGesture=user_gesture,
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description") or details.get("text")
            raise DevToolsError(f"JS の例外: {description}")
        return result["result"].get("value")

    def wait_until(self, expression: str, timeout_sec: float = PAGE_TIMEOUT_SEC) -> bool:
        """JS の式が真になるまで待ち、真になったかを返す。"""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                if self.evaluate(f"!!({expression})"):
                    return True
            except DevToolsError:
                # 画面の読み込み中などで評価できない間は、待つ
                pass
            time.sleep(POLL_SEC)
        return False

    def goto(self, url: str) -> bool:
        """URL を開き、画面が出るまで待って、出たかを返す。"""
        self.call("Page.navigate", url=url)
        return self.wait_until(PAGE_READY)

    def reload(self) -> bool:
        """今の画面を開き直し、画面が出るまで待って、出たかを返す。"""
        self.call("Page.reload")
        time.sleep(0.5)
        return self.wait_until(PAGE_READY)

    # === 要素の操作 ===

    @staticmethod
    def element(element_id: str) -> str:
        """項目 ID（data-element）の要素を引く JS の式を返す。"""
        return f'document.querySelector(\'[data-element="{element_id}"]\')'

    def click(self, element_id: str) -> None:
        """項目 ID の要素を押す（利用者の操作として）。"""
        self.evaluate(f"{self.element(element_id)}.click()", user_gesture=True)

    def text(self, element_id: str) -> str:
        """項目 ID の要素の文字を返す。"""
        return str(self.evaluate(f"{self.element(element_id)}.textContent"))

    def is_visible(self, element_id: str) -> bool:
        """項目 ID の要素が隠れていないか。"""
        return bool(self.evaluate(f"!{self.element(element_id)}.hidden"))

    def is_disabled(self, element_id: str) -> bool:
        """項目 ID の要素が押せないか。"""
        return bool(self.evaluate(f"{self.element(element_id)}.disabled"))

    def choose_file(self, data: bytes, name: str, mime: str) -> None:
        """ファイルを選んだ操作をする（ファイル送信の入力に、渡したファイルを入れて change を起こす）。"""
        encoded = base64.b64encode(data).decode()
        self.evaluate(
            f"""(() => {{
              const bytes = Uint8Array.from(atob('{encoded}'), (c) => c.charCodeAt(0));
              const input = {self.element('file_input')};
              const transfer = new DataTransfer();
              transfer.items.add(new File([bytes], {json.dumps(name)}, {{ type: {json.dumps(mime)} }}));
              input.files = transfer.files;
              input.dispatchEvent(new Event('change'));
            }})()""",
            user_gesture=True,
        )

    def choose_empty_file(self, size: int, name: str, mime: str) -> None:
        """大きさだけ指定した中身（0 のバイト列）のファイルを選んだ操作をする。"""
        self.evaluate(
            f"""(() => {{
              const input = {self.element('file_input')};
              const transfer = new DataTransfer();
              transfer.items.add(new File([new Uint8Array({size})], {json.dumps(name)}, {{ type: {json.dumps(mime)} }}));
              input.files = transfer.files;
              input.dispatchEvent(new Event('change'));
            }})()""",
            user_gesture=True,
        )

    def record_requests(self) -> None:
        """画面が送信する XMLHttpRequest の結果（ステータス・Content-Type・本文）を、window.__responses に控え始める。"""
        self.evaluate(
            """(() => {
              window.__responses = [];
              const send = XMLHttpRequest.prototype.send;
              XMLHttpRequest.prototype.send = function (...args) {
                this.addEventListener('loadend', () => window.__responses.push({
                  status: this.status,
                  content_type: this.getResponseHeader('content-type'),
                  body: this.responseText,
                }));
                return send.apply(this, args);
              };
            })()"""
        )

    def responses(self) -> list[dict[str, Any]]:
        """record_requests を始めてから返ってきた応答（返ってきた順）を返す。"""
        return list(self.evaluate("window.__responses"))

    def record_fetches(self) -> None:
        """画面が fetch で取りに行く結果の応答（ステータス・Content-Type・本文）を、window.__fetches に控え始める。"""
        self.evaluate(
            """(() => {
              window.__fetches = [];
              const realFetch = window.fetch.bind(window);
              window.fetch = async (...args) => {
                const response = await realFetch(...args);
                const body = await response.clone().text();
                window.__fetches.push({
                  status: response.status,
                  content_type: response.headers.get('content-type'),
                  body,
                });
                return response;
              };
            })()"""
        )

    def fetches(self) -> list[dict[str, Any]]:
        """record_fetches を始めてから返ってきた応答（返ってきた順）を返す。"""
        return list(self.evaluate("window.__fetches"))

    def watch_visible(self, element_id: str) -> None:
        """id の要素が一度でも見えたかを、window.__seen に控え始める。"""
        self.evaluate(
            f"""(() => {{
              window.__seen = false;
              const target = document.getElementById({json.dumps(element_id)});
              new MutationObserver(() => {{ if (!target.hidden) window.__seen = true; }})
                .observe(target, {{ attributes: true }});
            }})()"""
        )

    def was_seen(self) -> bool:
        """watch_visible を始めてから、その要素が一度でも見えたか。"""
        return bool(self.evaluate("window.__seen"))

    def advance_clock(self, milliseconds: int) -> None:
        """画面の時計（Date.now）を進める。"""
        self.evaluate(f"window.__advanceClock({milliseconds})")

    # === 画面の観測 ===

    def results(self) -> list[dict[str, Any]]:
        """結果の一覧（先頭が新しい件）を、元の音声・状態の文言・進み具合・起こした文字・失敗の理由・操作の有無の組で返す。"""
        value = self.evaluate(
            """JSON.stringify([...document.querySelectorAll('#results > li')].map((li) => {
              const field = (id) => li.querySelector(`[data-element="${id}"]`);
              const shown = (id) => (field(id).hidden ? '' : field(id).textContent);
              const pct = li.querySelector('.result__pct');
              return {
                source: field('result_source').textContent,
                status: field('result_status').hidden ? '' : li.querySelector('.result__status-text').textContent,
                percent: pct.hidden ? '' : pct.textContent,
                text: shown('result_text'),
                detail: shown('result_detail'),
                can_copy: !li.querySelector('.result__actions').hidden,
              };
            }))"""
        )
        return list(json.loads(value))

    def error(self) -> tuple[str, str] | None:
        """送信・録音の失敗の見出しと本文を返す。出ていなければ None。"""
        value = self.evaluate(
            """document.getElementById('send-error').hidden ? null : JSON.stringify([
              document.getElementById('send-error-title').textContent,
              document.getElementById('send-error-body').textContent,
            ])"""
        )
        if value is None:
            return None
        title, body = json.loads(value)
        return str(title), str(body)

    def kept_state(self) -> str | None:
        """画面に出ている端末内の音声の状態の文言を返す。出ていなければ None。"""
        value = self.evaluate(
            "document.getElementById('kept').hidden ? null : document.getElementById('kept-state').textContent"
        )
        return None if value is None else str(value)

    def preset_options(self) -> list[tuple[str, str]]:
        """用語集のプリセットの選択欄の選択肢を、値と表示文言の組で、並びのまま返す。"""
        value = self.evaluate(
            """JSON.stringify([...document.getElementById('preset-select').options].map(
              (option) => [option.value, option.text],
            ))"""
        )
        return [(str(option_value), str(text)) for option_value, text in json.loads(value)]

    def preset_value(self) -> str:
        """用語集のプリセットの選択欄で選ばれている値を返す（「設定に従う」は空文字）。"""
        return str(self.evaluate("document.getElementById('preset-select').value"))

    def select_preset(self, value: str) -> None:
        """用語集のプリセットの選択欄で、value の選択肢を選んだ操作をする。"""
        self.evaluate(
            f"""(() => {{
              const select = {self.element('preset_select')};
              select.value = {json.dumps(value)};
              select.dispatchEvent(new Event('change'));
            }})()""",
            user_gesture=True,
        )

    def preset_not_found_error(self) -> tuple[str, str] | None:
        """一覧に無いプリセットのエラーの見出しと本文を返す。出ていなければ None。"""
        value = self.evaluate(
            """document.getElementById('preset-not-found-error').hidden ? null : JSON.stringify([
              document.querySelector('#preset-not-found-error .web-error__title').textContent,
              document.getElementById('preset-not-found-body').textContent,
            ])"""
        )
        if value is None:
            return None
        title, body = json.loads(value)
        return str(title), str(body)

    # === 端末の保存 ===

    def kept_audio(self) -> dict[str, Any] | None:
        """IndexedDB に残った端末内の音声の項目（音声の中身は大きさだけ）を返す。無ければ None。"""
        value = self.evaluate(
            f"""(async () => {{
              {OPEN_STORE_JS}
              const {{ db, store }} = await openStore('readonly');
              const items = await new Promise((resolve, reject) => {{
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              }});
              db.close();
              return JSON.stringify(items.map((item) => ({{
                mime_type: item.mime_type, recorded_at: item.recorded_at, duration_sec: item.duration_sec,
                size_bytes: item.size_bytes, blob_size: item.blob.size, state: item.state, job_id: item.job_id,
              }})));
            }})()"""
        )
        items = json.loads(value)
        if len(items) > 1:
            raise DevToolsError("端末内の音声は直近 1 件だけ残るはずが、複数ある")
        return dict(items[0]) if items else None

    def seed_kept_audio(self, *, recorded_at: str, state: str, job_id: str | None) -> None:
        """端末（IndexedDB）に、保存日時を指定した音声を 1 件入れる。"""
        self.evaluate(
            f"""(async () => {{
              {OPEN_STORE_JS}
              const {{ db, transaction, store }} = await openStore('readwrite');
              store.put({{
                blob: new Blob([new Uint8Array(100)], {{ type: 'audio/webm' }}), mime_type: 'audio/webm',
                recorded_at: {json.dumps(recorded_at)}, duration_sec: 3, size_bytes: 100,
                state: {json.dumps(state)}, job_id: {json.dumps(job_id)},
              }}, {json.dumps(DB_KEY)});
              await new Promise((resolve, reject) => {{
                transaction.oncomplete = resolve;
                transaction.onerror = () => reject(transaction.error);
              }});
              db.close();
              return true;
            }})()"""
        )

    def stored_results(self) -> list[dict[str, Any]]:
        """localStorage に残った結果の一覧（新しい件が先頭）を返す。"""
        value = self.evaluate(f"localStorage.getItem({json.dumps(RESULTS_KEY)}) ?? '[]'")
        return list(json.loads(value))

    def seed_results(self, results: list[dict[str, Any]]) -> None:
        """localStorage に結果の一覧を入れる。"""
        self.evaluate(
            f"localStorage.setItem({json.dumps(RESULTS_KEY)}, {json.dumps(json.dumps(results))})"
        )

    def watch_clipboard(self) -> None:
        """画面がクリップボードへ書いた文字（書けたものだけ）を、window.__copied に控え始める。

        headless の Edge は、書いた文字を同じ画面から読み戻せないため、書き込みの呼び出しを見張る。
        """
        self.evaluate(
            """(() => {
              window.__copied = null;
              const realWrite = navigator.clipboard.writeText.bind(navigator.clipboard);
              navigator.clipboard.writeText = async (text) => {
                await realWrite(text);
                window.__copied = text;
              };
            })()"""
        )

    def copied_text(self) -> str | None:
        """watch_clipboard を始めてから、クリップボードへ書けた文字を返す。書いていなければ None。"""
        return self.evaluate("window.__copied")


class EdgeBrowser:
    """起動した Edge。タブを 1 つ持つ。"""

    def __init__(self, process: subprocess.Popen[bytes], page: BrowserPage) -> None:
        self.process = process
        self.page = page

    def grant_clipboard(self, origin: str) -> None:
        """そのオリジンに、クリップボードの読み書きを許す。"""
        self.page.call(
            "Browser.grantPermissions",
            origin=origin,
            permissions=["clipboardReadWrite", "clipboardSanitizedWrite"],
        )

    def allow_downloads(self, download_dir: Path) -> None:
        """ダウンロードを確認なしで download_dir へ保存させる。"""
        self.page.call(
            "Browser.setDownloadBehavior", behavior="allow", downloadPath=str(download_dir)
        )

    def close(self) -> None:
        """Edge を終わらせる。"""
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def _free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ返す。"""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _connect(port: int) -> BrowserPage:
    """DevTools が立つまで待って、最初のタブに繋ぐ。"""
    deadline = time.monotonic() + LAUNCH_TIMEOUT_SEC
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as response:  # noqa: S310 自分で立てた Edge の DevTools
                tabs = json.load(response)
            page = next(tab for tab in tabs if tab["type"] == "page")
            return BrowserPage(page["webSocketDebuggerUrl"])
        except (OSError, StopIteration, KeyError) as error:
            last_error = error
            time.sleep(POLL_SEC * 2)
    raise DevToolsError(f"Edge の DevTools に繋がらない: {last_error}")


@contextmanager
def launch_edge(
    profile_dir: Path, *, fake_microphone_wav: Path | None = None
) -> Iterator[EdgeBrowser]:
    """Edge を headless・偽のマイクで起動して、タブを 1 つ操作できる状態で返す。抜けるときに終わらせる。"""
    port = _free_port()
    arguments = [
        EDGE_PATH,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
    ]
    if fake_microphone_wav is not None:
        arguments.append(f"--use-file-for-fake-audio-capture={fake_microphone_wav}")
    process = subprocess.Popen(  # noqa: S603 固定の Edge に自分で組んだ引数を渡す
        [*arguments, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        browser = EdgeBrowser(process, _connect(port))
    except DevToolsError:
        process.kill()
        raise
    try:
        yield browser
    finally:
        browser.close()


def open_page(browser: EdgeBrowser, origin: str) -> BrowserPage:
    """origin（`http://localhost:{ポート}`）の `/web/` を開き、クリップボードを許して、タブを返す。画面が出なければ例外にする。"""
    browser.grant_clipboard(origin)
    if not browser.page.goto(f"{origin}/web/"):
        raise DevToolsError("画面が出なかった")
    return browser.page


def wait_for(condition: Callable[[], bool], timeout_sec: float = PAGE_TIMEOUT_SEC) -> bool:
    """condition が真になるまで待ち、真になったかを返す。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(POLL_SEC)
    return condition()
