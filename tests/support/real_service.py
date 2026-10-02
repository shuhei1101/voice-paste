"""実機のテスト（E2E・実機の非機能要件テスト）が使う、本物の常駐サービスの起動と API の呼び出し。

`python -m voice_paste --data-dir {一時フォルダ}` を子プロセスとして起動し（build_handlers の配線・実機のマイク・
ローカルの Whisper を通る）、トークンのファイルを読んで API を叩く。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / "src"
TOKEN_FILE_NAME = "api_token"
STARTUP_TIMEOUT_SEC = 120.0
"""常駐サービスがトークンのファイルを書くまで（モデルの読み込みを含む）待つ上限。"""

SHUTDOWN_TIMEOUT_SEC = 30.0
"""終了の合図を送ってから、サービスが終わるまで待つ上限。"""

REQUEST_TIMEOUT_SEC = 10.0
LOOPBACK = "127.0.0.1"
POLL_SEC = 0.1
LOG_TAIL_CHARS = 3000


def _free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ返す。"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


@dataclass
class RealService:
    """起動した本物の常駐サービス。"""

    data_dir: Path
    process: subprocess.Popen[bytes]
    token: str
    port: int
    http: httpx.Client

    @classmethod
    def launch(
        cls, data_dir: Path, *, extra_settings: str = "", startup_timeout_sec: float = STARTUP_TIMEOUT_SEC
    ) -> RealService:
        """data_dir に設定を書いて常駐サービスを起動し、トークンのファイルが書かれるまで待つ。"""
        # 1. API のポートを空きポートにした設定を書く（extra_settings は TOML の続き）
        data_dir.mkdir(parents=True, exist_ok=True)
        port = _free_port()
        (data_dir / "settings.toml").write_text(
            f"[api]\nport = {port}\n\n{extra_settings}\n", encoding="utf-8"
        )

        # 2. このリポジトリの src を使って、新しいプロセスグループで起動する（終了の合図 Ctrl+Break を送れるように）
        env = dict(os.environ, PYTHONPATH=str(SOURCE_DIR), PYTHONIOENCODING="utf-8")
        stdout = (data_dir / "stdout.log").open("wb")
        process = subprocess.Popen(  # noqa: S603 自分のインタープリタでこのリポジトリのモジュールを起動する
            [sys.executable, "-m", "voice_paste", "--data-dir", str(data_dir)],
            env=env,
            cwd=REPO_ROOT,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        # 3. トークンのファイル（待ち受けを始めた後に書かれる）を待つ
        token_file = data_dir / TOKEN_FILE_NAME
        deadline = time.monotonic() + startup_timeout_sec
        while not token_file.exists():
            if process.poll() is not None or time.monotonic() > deadline:
                process.kill()
                raise RuntimeError(
                    "常駐サービスが起動しなかった:\n" + cls._tail(data_dir / "stdout.log")
                )
            time.sleep(POLL_SEC)
        info = json.loads(token_file.read_text(encoding="utf-8"))
        http = httpx.Client(base_url=f"http://{LOOPBACK}:{info['port']}", timeout=REQUEST_TIMEOUT_SEC)
        return cls(data_dir=data_dir, process=process, token=info["token"], port=info["port"], http=http)

    @staticmethod
    def _tail(path: Path) -> str:
        """ログの終わりの部分を返す。"""
        return path.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL_CHARS:]

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """API へ POST する。authorized なら起動ごとのトークンを付ける。"""
        merged = {"Authorization": f"Bearer {self.token}"} if authorized else {}
        merged.update(headers or {})
        return self.http.post(path, json=json_body, headers=merged)

    def start_session(self, callback_url: str) -> tuple[httpx.Response, float]:
        """API の開始を呼び、応答と、応答までにかかったミリ秒を返す。"""
        started = time.perf_counter()
        response = self.post("/sessions", json_body={"callback_url": callback_url})
        return response, (time.perf_counter() - started) * 1000

    def log_records(self) -> list[dict[str, Any]]:
        """常駐サービスのログ（JSON Lines）の全ての行を読む。"""
        return [
            json.loads(line)
            for log_file in sorted((self.data_dir / "log").glob("*.log"))
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")
        ]

    def history_files(self, suffix: str) -> list[Path]:
        """履歴に残ったファイルのうち、拡張子が suffix のものを返す。"""
        return sorted((self.data_dir / "history").rglob(f"*{suffix}"))

    def is_running(self) -> bool:
        """常駐サービスのプロセスが動いているか。"""
        return self.process.poll() is None

    def shutdown(self) -> int | None:
        """終了の合図（Ctrl+Break）を送って終わりを待ち、終了コードを返す。待ちきれなければ止める。"""
        self.http.close()
        if self.process.poll() is None:
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                self.process.wait(timeout=SHUTDOWN_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        return self.process.returncode
