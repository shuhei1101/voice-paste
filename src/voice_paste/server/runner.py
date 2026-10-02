"""uvicorn を専用のスレッドで動かし、待ち受けを始められたかを確かめる。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)

LISTEN_HOST: str = "127.0.0.1"
"""待ち受けるホスト。外部から届かないよう loopback に固定する。"""

POLL_INTERVAL_SEC: float = 0.01
"""待ち受けの開始を確かめる間隔。"""

STOP_TIMEOUT_SEC: float = 5.0
"""止めるときにスレッドの終わりを待つ上限。"""

THREAD_NAME: str = "api-server"
"""uvicorn を動かすスレッドの名前。"""


class ApiServerRunner:
    """uvicorn.Server を専用のスレッドで動かす。"""

    def __init__(self, app: FastAPI, port: int) -> None:
        """app と待ち受けのポートから、127.0.0.1 固定でアクセスログを出さない uvicorn のサーバーを作る。"""
        self._port = port
        # log_config=None: uvicorn のログの設定は使わず、アプリのログの設定（setup_logging）に任せる
        config = uvicorn.Config(
            app, host=LISTEN_HOST, port=port, access_log=False, log_config=None
        )
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    def start(self, timeout_sec: float) -> bool:
        """スレッドで serve() を始め、started が True になるかスレッドが終わるまで待ち、待ち受けを始められたかを返す。"""
        # 1. スレッドで serve() を始める
        thread = threading.Thread(target=self._serve, name=THREAD_NAME, daemon=True)
        self._thread = thread
        thread.start()

        # 2. started が True になるか、スレッドが終わるか、timeout_sec が過ぎるまで待つ
        deadline = time.monotonic() + timeout_sec
        while not self._server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SEC)
        if self._server.started:
            return True

        # 3. 始められなかった（uvicorn は待ち受けに失敗しても例外を出さずスレッドを終える）
        logger.error(f"API の待ち受けを始められなかった（ポート: {self._port}）")
        self._server.should_exit = True
        return False

    def _serve(self) -> None:
        """スレッドの中で uvicorn を動かす。待ち受けに失敗すると uvicorn が SystemExit で終わるため、握ってスレッドを終える。"""
        try:
            asyncio.run(self._server.serve())
        except SystemExit:
            # 待ち受けの失敗は uvicorn がログに書き済みで、start が started で判断する
            return

    def stop(self) -> None:
        """should_exit を立ててスレッドの終わりを待つ。始めていなければ何もしない。"""
        thread = self._thread
        if thread is None:
            return
        self._server.should_exit = True
        thread.join(timeout=STOP_TIMEOUT_SEC)
        logger.info(f"API の待ち受けを止めた（ポート: {self._port}）")
