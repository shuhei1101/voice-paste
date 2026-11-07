"""WSL の中の Haas の文字起こしのサーバーを、必要なら wsl.exe で起動し、自分が起動したサーバーだけを止める。"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx

from voice_paste.integrations.haas.transcriber import HAAS_CONNECT_TIMEOUT_SEC, HTTP_OK
from voice_paste.shared.constants import REPO_ROOT
from voice_paste.shared.errors import EngineError
from voice_paste.shared.settings import HaasSettings

logger = logging.getLogger(__name__)

HAAS_START_TIMEOUT_SEC: float = 60.0
"""サーバーを起動してから応答するまで待つ秒数。"""

HAAS_HEALTH_INTERVAL_SEC: float = 0.5
"""起動を待つ間に GET /health を送信する間隔（秒）。"""

HAAS_SERVER_DIR: Path = REPO_ROOT / "haas_server"
"""リポジトリの haas_server フォルダ。wsl.exe の --cd に渡す。"""

WSL_EXECUTABLE: str = "wsl.exe"
"""サーバーを起動するコマンド。"""

type StartupItem = Literal["model", "dtype", "device"]
"""サーバーの起動で決まる項目。"""

STARTUP_ITEMS: tuple[StartupItem, ...] = ("model", "dtype", "device")
"""動いているサーバーと設定で比べる項目（並びは通知に出す順）。"""


class HaasServer:
    """Haas の文字起こしのサーバーの起動と停止。起動の前から応答するサーバーは使うだけで止めない。"""

    def __init__(
        self,
        *,
        settings: HaasSettings,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """ディストリビューション・ポート・モデル・計算の精度・装置を受ける。popen・clock・transport はテストで差し替える。"""
        self._settings = settings
        self._popen = popen
        self._clock = clock
        self._transport = transport
        self._stopped = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None

    def ensure_started(self) -> tuple[StartupItem, ...]:
        """接続先が応答すれば設定と起動の引数を比べてそのまま使い、応答が無ければ wsl.exe で起動して応答を待つ。

        起動の前から動いていたサーバーのうち設定と違う項目を model・dtype・device の順で返す（起動したときは空）。
        """
        # 1. 動いているサーバーがあれば、設定と比べてそのまま使う
        health = self._read_health()
        if health is not None:
            logger.info(f"動いている Haas のサーバーを使う（ポート {self._settings.port}）")
            return self._compare_with_settings(health)

        # 2. wsl.exe でサーバーを起動する
        process = self._start_process()

        # 3. 応答を待つ。起動スクリプトの失敗と stop で打ち切る
        started = self._clock()
        while self._clock() - started < HAAS_START_TIMEOUT_SEC:
            if self._stopped.wait(HAAS_HEALTH_INTERVAL_SEC):
                process.terminate()
                raise EngineError("Haas のサーバーの起動を待つ間に止められた")
            if self._read_health() is not None:
                logger.info(
                    f"Haas のサーバーを起動した（{self._clock() - started:.1f} 秒・ポート {self._settings.port}）"
                )
                return ()
            return_code = process.poll()
            if return_code:
                raise EngineError(f"Haas のサーバーの起動に失敗した（終了コード {return_code}）")

        # 4. 読み込み中のサーバーが残って GPU を使い続けないよう、wsl.exe を終わらせる
        process.terminate()
        raise EngineError(f"Haas のサーバーが {HAAS_START_TIMEOUT_SEC:.0f} 秒以内に応答しない")

    def stop(self) -> None:
        """このインスタンスが起動したサーバーを止める。起動の待ちも打ち切る。応答は待たない。"""
        self._stopped.set()
        process = self._process
        # 起動の前から動いていたサーバーは止めない
        if process is None:
            return
        try:
            with self._client() as client:
                client.post(self._url("/shutdown"))
        except httpx.HTTPError as error:
            process.terminate()
            logger.warning(
                f"Haas のサーバーへ /shutdown が届かないため wsl.exe を終わらせた（{type(error).__name__}）"
            )

    def _start_process(self) -> subprocess.Popen[bytes]:
        """wsl.exe でサーバーの起動スクリプトを起動し、控える。"""
        settings = self._settings
        distribution = ["-d", settings.distribution] if settings.distribution else []
        args = [
            WSL_EXECUTABLE,
            *distribution,
            "--cd",
            str(HAAS_SERVER_DIR),
            "-e",
            "bash",
            "start.sh",
            str(settings.port),
            settings.model,
            settings.dtype,
            settings.device,
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._process = self._popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as error:
            raise EngineError(f"wsl.exe を起動できない（{type(error).__name__}）") from error
        return self._process

    def _read_health(self) -> dict[str, object] | None:
        """GET /health を送信し、200 なら応答の JSON を返す。接続できない・200 以外・JSON でなければ None。"""
        try:
            with self._client() as client:
                response = client.get(self._url("/health"))
        except httpx.HTTPError:
            return None
        if response.status_code != HTTP_OK:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _compare_with_settings(self, health: dict[str, object]) -> tuple[StartupItem, ...]:
        """動いているサーバーの起動の引数を設定の値と文字列で比べ、違う項目を返す。応答に無い項目も違うとする。"""
        settings = self._settings
        expected: dict[StartupItem, str] = {
            "model": settings.model,
            "dtype": settings.dtype,
            "device": settings.device,
        }
        differs = tuple(item for item in STARTUP_ITEMS if health.get(item) != expected[item])
        if differs:
            detail = "・".join(
                f"{item} {health.get(item)} → {expected[item]}" for item in differs
            )
            logger.warning(
                f"動いている Haas のサーバーが設定と違う（{detail}。"
                "設定の値で動かすにはサーバーを止めてから起動し直す）"
            )
        return differs

    def _client(self) -> httpx.Client:
        """サーバーへの接続を作る。"""
        return httpx.Client(timeout=HAAS_CONNECT_TIMEOUT_SEC, transport=self._transport)

    def _url(self, path: str) -> str:
        """サーバーのパスの URL を返す。"""
        return f"http://127.0.0.1:{self._settings.port}{path}"
