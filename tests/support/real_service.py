"""実機のテスト（E2E・実機の非機能要件テスト）が使う、本物の常駐サービスの起動と API の呼び出し。

`python -m voice_paste --data-dir {一時フォルダ}` を子プロセスとして起動し（build_handlers の配線・
ローカルの Whisper を通る。Qt は offscreen で、画面もトレイのアイコンも実機に出ない）、トークンのファイルを読んで API を叩く。
録音開始のホットキーは普段使わない組み合わせにして起動し、ユーザーの打鍵で実機のマイクを開く録音を始めない。
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
QT_PLATFORM_ENV = "QT_QPA_PLATFORM"
"""Qt が画面の出し先を選ぶ環境変数。`offscreen` だと画面もトレイのアイコンも実機に出ない。"""
QT_PLATFORM_OFFSCREEN = "offscreen"
"""画面もトレイのアイコンも実機に出さない Qt のプラットフォーム。"""
UNUSED_START_HOTKEY = "<ctrl>+<alt>+<shift>+<f12>"
"""テストの常駐アプリが録音開始に受ける、普段使わないホットキー（既定のままだと、ユーザーの打鍵で録音が始まる）。"""
STARTUP_TIMEOUT_SEC = 120.0
"""常駐サービスがトークンのファイルを書くまで（モデルの読み込みを含む）待つ上限。"""

SHUTDOWN_TIMEOUT_SEC = 30.0
"""終了の合図を送ってから、サービスが終わるまで待つ上限。"""

REQUEST_TIMEOUT_SEC = 10.0
LOOPBACK = "127.0.0.1"
POLL_SEC = 0.1
LOG_TAIL_CHARS = 3000


def free_port() -> int:
    """127.0.0.1 の空きポートを 1 つ返す。"""
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


def read_token_file(data_dir: Path) -> dict[str, Any] | None:
    """data_dir の起動ごとのトークンのファイル（トークンとポート）を読む。まだ無い・書きかけなら None。"""
    try:
        info = json.loads((data_dir / TOKEN_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dict(info) if isinstance(info, dict) else None


def post_to_api(
    http: httpx.Client,
    token: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    authorized: bool = True,
) -> httpx.Response:
    """API へ POST する。authorized なら起動ごとのトークンを付ける。"""
    merged = {"Authorization": f"Bearer {token}"} if authorized else {}
    merged.update(headers or {})
    return http.post(path, json=json_body, headers=merged)


def read_log_records(data_dir: Path) -> list[dict[str, Any]]:
    """data_dir のログ（JSON Lines）の全ての行を、書かれた順に読む。"""
    return [
        json.loads(line)
        for log_file in sorted((data_dir / "log").glob("*.log"))
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("{")
    ]


def settings_text(api_port: int, extra_settings: str = "") -> str:
    """テストの常駐アプリの settings.toml の中身（API のポートと、録音開始のホットキー。extra_settings は TOML の続き）。"""
    return (
        f'[api]\nport = {api_port}\n\n[hotkeys]\nstart = "{UNUSED_START_HOTKEY}"\n\n{extra_settings}\n'
    )


def spawn_process(
    data_dir: Path,
    *,
    stdout_name: str = "stdout.log",
) -> subprocess.Popen[bytes]:
    """このリポジトリの src で `python -m voice_paste --data-dir {data_dir}` を、新しいプロセスグループで起動する。

    終了の合図 Ctrl+Break を送れるよう新しいプロセスグループにする。標準出力は data_dir の stdout_name へ書く
    （同じ data_dir で続けて起動するときは、前のプロセスの出力を消さないよう名前を変える）。
    常駐アプリは offscreen で起動し、画面もトレイのアイコンも実機に出さない。
    """
    env = dict(
        os.environ,
        PYTHONPATH=str(SOURCE_DIR),
        PYTHONIOENCODING="utf-8",
        **{QT_PLATFORM_ENV: QT_PLATFORM_OFFSCREEN},
    )
    stdout = (data_dir / stdout_name).open("wb")
    return subprocess.Popen(  # noqa: S603 自分のインタープリタでこのリポジトリのモジュールを起動する
        [sys.executable, "-m", "voice_paste", "--data-dir", str(data_dir)],
        env=env,
        cwd=REPO_ROOT,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


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
        cls,
        data_dir: Path,
        *,
        extra_settings: str = "",
        startup_timeout_sec: float = STARTUP_TIMEOUT_SEC,
        port: int | None = None,
        wait_for_api: bool = True,
    ) -> RealService:
        """data_dir に設定を書いて常駐サービスを起動し、トークンのファイルが書かれるまで待つ。

        port を渡せばそのポートを、無ければ空きポートを API の待ち受けにする。
        wait_for_api が False なら、トークンのファイルを待たずに返す（起動に失敗する・API を使えない起動の確認用。
        返す RealService のトークンは空）。
        """
        # 1. API のポートを書いた設定を置く（extra_settings は TOML の続き）
        data_dir.mkdir(parents=True, exist_ok=True)
        api_port = free_port() if port is None else port
        (data_dir / "settings.toml").write_text(
            settings_text(api_port, extra_settings), encoding="utf-8"
        )

        # 2. 起動する
        process = spawn_process(data_dir)
        if not wait_for_api:
            base_url = f"http://{LOOPBACK}:{api_port}"
            http = httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT_SEC)
            return cls(data_dir=data_dir, process=process, token="", port=api_port, http=http)

        # 3. トークンのファイル（待ち受けを始めた後に書かれる）を待つ
        return cls.attach(data_dir, process, startup_timeout_sec=startup_timeout_sec)

    @classmethod
    def attach(
        cls,
        data_dir: Path,
        process: subprocess.Popen[bytes],
        *,
        startup_timeout_sec: float = STARTUP_TIMEOUT_SEC,
    ) -> RealService:
        """起動したプロセスのトークンのファイルが書かれるまで待ち、読んだトークンとポートで API を呼べる RealService にする。

        data_dir に前の起動のトークンのファイルが残っていれば、それを読んでしまう。
        同じ置き場所で続けて起動したときは、後のプロセスが待機中になったのを確かめてから呼ぶ。
        """
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
        base_url = f"http://{LOOPBACK}:{info['port']}"
        http = httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT_SEC)
        return cls(
            data_dir=data_dir, process=process, token=info["token"], port=info["port"], http=http
        )

    @staticmethod
    def _tail(path: Path) -> str:
        """ログの終わりの部分を返す。"""
        return path.read_text(encoding="utf-8", errors="replace")[-LOG_TAIL_CHARS:]

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        authorized: bool = True,
    ) -> httpx.Response:
        """API へ POST する。authorized なら起動ごとのトークンを付ける。"""
        return post_to_api(
            self.http,
            self.token,
            path,
            json_body=json_body,
            headers=headers,
            authorized=authorized,
        )

    def start_session(self, callback_url: str) -> tuple[httpx.Response, float]:
        """API の開始を呼び、応答と、応答までにかかったミリ秒を返す。"""
        started = time.perf_counter()
        response = self.post("/sessions", json_body={"callback_url": callback_url})
        return response, (time.perf_counter() - started) * 1000

    def log_records(self) -> list[dict[str, Any]]:
        """常駐サービスのログ（JSON Lines）の全ての行を読む。"""
        return read_log_records(self.data_dir)

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
