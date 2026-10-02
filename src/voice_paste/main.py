"""起動の入口。設定を読み、各 feature を関数で配線し（composition root）、API サーバーを立てて終了の合図を待つ。"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from types import FrameType
from typing import Literal

from voice_paste.features.correction import apply_glossary, load_glossary
from voice_paste.features.history import append_text, discard_temporary, save_recording
from voice_paste.features.outputs import OUTPUTS, OutputSpec, deliver, is_callback_allowed
from voice_paste.features.outputs.callback.client import post_json
from voice_paste.features.outputs.registry import CALLBACK_OUTPUT_ID
from voice_paste.features.recording import Recorder
from voice_paste.features.recording.client import open_input
from voice_paste.features.session import (
    Session,
    SessionApiDeps,
    SessionDeps,
    SessionManager,
)
from voice_paste.features.session.types import NotifyFn
from voice_paste.features.transcription.service import transcribe
from voice_paste.integrations.volume.adapter import lower_volume, restore_volume
from voice_paste.integrations.whisper.client import WhisperWorkerClient
from voice_paste.runtime.timer import RepeatingTimer
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token, write_token_file
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.env_migration import migrate_env
from voice_paste.shared.errors import EngineError, SettingsError, StartupError
from voice_paste.shared.logger import local_today, purge_old_logs, setup_logging
from voice_paste.shared.settings import Settings, load_settings, save_settings
from voice_paste.shared.types import TranscriptionOutcome

logger = logging.getLogger(__name__)

STARTUP_LOG_LEVEL: str = "INFO"
"""設定を読むまでのログのレベル。"""

EXIT_OK: int = 0
"""正常終了の終了コード。"""

EXIT_FAILED: int = 1
"""起動に失敗した終了コード。"""

API_START_TIMEOUT_SEC: float = 5.0
"""ApiServerRunner.start が started を待つ上限。uvicorn の起動の実測が無いため仮に置く。"""

SESSION_LIMIT_CHECK_INTERVAL_SEC: float = 1.0
"""上限での打ち切りを確かめる間隔。打ち切りの遅れはこの間隔までで、上限時間に対して無視できる。"""

API_SESSION_LIMIT_SEC: int = 600
"""API のセッションの上限時間。非機能要件の API のセッションの上限時間の決定値。"""

CALLBACK_TIMEOUT_SEC: float = 1.5
"""返送の 1 回の POST のタイムアウト。非機能要件の返送のタイムアウトと再送の決定値。"""

CALLBACK_RETRY_COUNT: int = 3
"""返送を最初の 1 回の後に再送する回数。非機能要件の返送のタイムアウトと再送の決定値。"""

CALLBACK_RETRY_BASE_SEC: float = 1.0
"""返送の再送の間隔の基数（回ごとに 2 倍にし、フルジッターをかける）。非機能要件の決定値。"""

WORKER_READY_TIMEOUT_SEC: float = 10.0
"""文字起こしワーカーの立て直しで ready を待つ上限。非機能要件の文字起こしワーカーの立て直しの時間の決定値。"""

WORKER_STOP_TIMEOUT_SEC: float = 3.0
"""文字起こしワーカーの終わりを待つ時間。非機能要件の文字起こしワーカーの終わりを待つ時間の決定値。"""

GLOSSARY_FILE_NAME: str = "yogo.csv"
"""用語集のパスを設定しないときに、設定ファイルと同じフォルダから読む用語集の名前。"""

SHUTDOWN_POLL_SEC: float = 1.0
"""終了の合図を待つときに、メインスレッドがシグナルを受けられるよう区切る秒数。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CliArgs:
    """`python -m voice_paste` に渡した引数。"""

    data_dir: Path | None
    migrate_env: Path | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Handlers:
    """入口（API・ホットキー・画面）が使う配線済みのもの。"""

    session_manager: SessionManager
    """セッション管理。"""

    session_api: SessionApiDeps
    """API サーバーへ渡すセッションの API の依存（設定の許可ホストを部分適用した返送先の確かめを含む）。"""

    settings: Settings
    """読み込んだ設定。"""

    stop_engine: Callable[[], None]
    """文字起こしのエンジンを止める。終了時に呼ぶ。"""


def parse_args(argv: list[str]) -> CliArgs:
    """argparse で `--data-dir` と `--migrate-env` を読む。"""
    parser = argparse.ArgumentParser(prog="voice_paste")
    # 並走の間は普段使いの置き場所へ書かないよう、置き場所を必須にする
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="設定・履歴・ログ・一時の音声・トークンを置くフォルダ",
    )
    parser.add_argument(
        "--migrate-env",
        type=Path,
        default=None,
        help="設定ファイルへ移す .env",
    )
    namespace = parser.parse_args(argv)
    return CliArgs(data_dir=namespace.data_dir, migrate_env=namespace.migrate_env)


def log_notify(
    event: Literal[
        "state_changed",
        "busy",
        "microphone_unavailable",
        "transcription_failed",
        "delivery_failed",
        "api_unavailable",
    ],
    detail: str | None = None,
) -> None:
    """画面とトレイが入るまでの NotifyFn。知らせの種類と理由をログに書く。"""
    # 状態の変化は INFO、それ以外（失敗・断り）は WARNING
    level = logging.INFO if event == "state_changed" else logging.WARNING
    logger.log(level, f"ユーザーへの知らせ（{event}・{detail}）")


def wait_for_shutdown_signal() -> None:
    """Ctrl+C（SIGINT）か Ctrl+Break（SIGBREAK）が来るまで待つ。画面とトレイが入るまでの終わり方。"""
    stopped = threading.Event()

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        """シグナルを受けたら終了の合図を立てる。"""
        logger.info(f"終了の合図を受けた（シグナル: {signum}）")
        stopped.set()

    # 1. SIGINT と（あれば）SIGBREAK のハンドラで合図を立てる
    signal.signal(signal.SIGINT, _on_signal)
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, _on_signal)

    # 2. 立つまで 1 秒ずつ待つ（メインスレッドがシグナルを受けられるよう、上限なしの wait にしない）
    while not stopped.wait(SHUTDOWN_POLL_SEC):
        pass


def _local_now() -> datetime:
    """今の時刻を、この端末のタイムゾーンつきで返す。"""
    return datetime.now(UTC).astimezone()


def _jitter(upper: float) -> float:
    """0 以上 upper 以下の乱数を返す（再送の間隔のフルジッター）。"""
    return random.uniform(0, upper)  # noqa: S311 暗号用途ではない


def _correct(text: str, *, glossary_path: Path) -> str:
    """文字起こしのたびに用語集を読み直して補正する。"""
    return apply_glossary(text, load_glossary(glossary_path))


def _deliver_session(
    session: Session,
    outcome: TranscriptionOutcome,
    *,
    enabled_ids: frozenset[str],
    outputs: tuple[OutputSpec, ...],
) -> None:
    """Session を入口・選んだ出力先・返送先に分けて、出力先の deliver へ渡す（出力先はセッションを import しない）。"""
    deliver(
        session.entry,
        session.output_id,
        session.callback_url,
        outcome,
        enabled_ids=enabled_ids,
        outputs=outputs,
    )


def _wire_outputs(settings: Settings) -> tuple[OutputSpec, ...]:
    """出力先の一覧のうち、呼び出し元へ返す出力先に再送などの注入を部分適用して返す。"""
    allowed_hosts = frozenset(settings.api.allowed_callback_hosts)
    wired: list[OutputSpec] = []
    for spec in OUTPUTS:
        # 呼び出し元へ返す出力先だけ、タイムアウトを部分適用した post_json・許可ホスト・再送の設定を渡す
        if spec.id == CALLBACK_OUTPUT_ID:
            handler = partial(
                spec.handler,
                post=partial(post_json, timeout_sec=CALLBACK_TIMEOUT_SEC),
                allowed_hosts=allowed_hosts,
                retry_count=CALLBACK_RETRY_COUNT,
                retry_base_sec=CALLBACK_RETRY_BASE_SEC,
                sleep=time.sleep,
                jitter=_jitter,
            )
            spec = replace(spec, handler=handler)
        wired.append(spec)
    return tuple(wired)


def build_handlers(settings: Settings, paths: AppPaths, notify: NotifyFn) -> Handlers:
    """設定からエンジン・録音機・出力先・履歴を組み立て、SessionDeps を作って SessionManager と SessionApiDeps を返す。"""
    # 1. 設定のエンジン（local_whisper）のワーカーを作って起動する
    engine = WhisperWorkerClient(
        settings=settings.transcription.local_whisper,
        ready_timeout_sec=WORKER_READY_TIMEOUT_SEC,
        log_dir=paths.log_dir,
        stop_timeout_sec=WORKER_STOP_TIMEOUT_SEC,
    )
    try:
        engine.start()
    except EngineError as error:
        raise StartupError(f"文字起こしのエンジンを準備できませんでした: {error}") from error

    # 2. 録音機に音量とマイクの入力の関数を渡す
    recorder = Recorder(
        lower_volume=lower_volume,
        restore_volume=restore_volume,
        open_input=open_input,
        get_settings=lambda: settings.recording,
    )

    # 3. 出力先を配線し、Session を分けて渡すアダプタを作る
    enabled_ids = frozenset(output.id for output in settings.outputs if output.enabled)
    deliver_session = partial(
        _deliver_session, enabled_ids=enabled_ids, outputs=_wire_outputs(settings)
    )

    # 4. 用語集を文字起こしのたびに読み直す補正を作る
    glossary_path = settings.glossary_path or paths.settings_file.parent / GLOSSARY_FILE_NAME

    # 5. SessionDeps を組み、API のセッションの上限時間と共に SessionManager を作る
    deps = SessionDeps(
        start_recording=recorder.start,
        pause_recording=recorder.pause,
        resume_recording=recorder.resume,
        stop_recording=recorder.stop,
        discard_recording=recorder.discard,
        save_recording=partial(
            save_recording,
            history_enabled=settings.history.enabled,
            paths=paths,
            now=_local_now,
        ),
        transcribe=partial(transcribe, engine=engine.transcribe),
        correct=partial(_correct, glossary_path=glossary_path),
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=notify,
        now=_local_now,
        discard_temporary=partial(discard_temporary, paths=paths),
    )
    session_manager = SessionManager(deps, timedelta(seconds=API_SESSION_LIMIT_SEC))

    # 6. SessionManager と、設定の許可ホストを部分適用した返送先の確かめを SessionApiDeps に束ねる
    session_api = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=partial(
            is_callback_allowed, allowed_hosts=frozenset(settings.api.allowed_callback_hosts)
        ),
    )
    return Handlers(
        session_manager=session_manager,
        session_api=session_api,
        settings=settings,
        stop_engine=engine.stop,
    )


def main(
    argv: list[str] | None = None,
    *,
    wait_for_shutdown: Callable[[], None] = wait_for_shutdown_signal,
) -> int:
    """常駐サービスを起動し、終了の合図まで待って片付け、終了コードを返す。"""
    # 1. 起動の引数を読む
    args = parse_args(sys.argv[1:] if argv is None else argv)

    # 2. 置き場所を決め、ログを設定する
    paths = resolve_app_paths(args.data_dir)
    setup_logging(paths.log_dir, STARTUP_LOG_LEVEL)

    # 3. `--migrate-env` が渡されていれば、.env を移して書く
    if args.migrate_env is not None:
        # 設定ファイルが既にあれば、書き換えた設定を上書きしないよう移さない
        if paths.settings_file.exists():
            logger.error(f"設定ファイルが既にあるため .env を移さなかった（{paths.settings_file}）")
            return EXIT_FAILED
        try:
            save_settings(paths.settings_file, migrate_env(args.migrate_env))
        except SettingsError as error:
            logger.error(f".env を移せなかった（{error}）")
            return EXIT_FAILED
        logger.info(f".env を設定ファイルへ移した（{args.migrate_env}、{paths.settings_file}）")

    # 4. 設定を読む
    try:
        settings = load_settings(paths.settings_file)
    except SettingsError as error:
        logger.error(f"起動に失敗した（{error}）")
        return EXIT_FAILED

    # 5. ルートロガーのレベルを設定のログのレベルにし、保持期間で古いログを消す
    logging.getLogger().setLevel(settings.logging.level)
    purge_old_logs(paths.log_dir, settings.logging.retention_days, local_today())

    # 読んだ設定の要点をログに書く（API キーは書かない）
    enabled_outputs = [output.id for output in settings.outputs if output.enabled]
    logger.info(
        f"設定を読んだ（{paths.settings_file}、エンジン: {settings.transcription.engine}、"
        f"オンの出力先: {', '.join(enabled_outputs)}）"
    )

    # 6. 配線する（エンジンを準備できなければ録音を受け付けられないので終える）
    try:
        handlers = build_handlers(settings, paths, log_notify)
    except StartupError as error:
        logger.error(f"起動に失敗した（{error}）")
        return EXIT_FAILED

    # 7. トークンを作り、API サーバーを起動する
    token = create_token()
    port = settings.api.port
    app = build_fastapi(handlers.session_api, token, port)
    runner = ApiServerRunner(app, port)
    if not runner.start(API_START_TIMEOUT_SEC):
        # 待ち受けを始められなかった: トークンのファイルは書かず（ほかの起動のトークンを上書きしない）、知らせてエンジンを止める
        log_notify("api_unavailable", str(port))
        handlers.stop_engine()
        return EXIT_FAILED
    write_token_file(paths.token_file, port, token)

    # 8. 上限の打ち切りを間隔ごとに呼ぶ
    timer = RepeatingTimer(
        handlers.session_manager.truncate_if_expired, SESSION_LIMIT_CHECK_INTERVAL_SEC
    )
    timer.start()
    logger.info(f"常駐サービスを始めた（API のポート: {port}）")

    # 9. 終了の合図を待つ
    wait_for_shutdown()

    # 10. 新しい開始が来ないようにタイマー・API サーバーを先に止め、録音を捨て、エンジンを止める
    timer.stop()
    runner.stop()
    handlers.session_manager.close()
    handlers.stop_engine()
    logger.info("常駐サービスを終えた")
    return EXIT_OK
