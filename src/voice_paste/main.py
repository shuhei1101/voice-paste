"""起動の入口。設定を読み、各 feature を関数で配線し（composition root）、API・ホットキー・トレイを立てて画面のイベントループを回す。"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from PySide6.QtCore import QMetaObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from voice_paste.features.correction import apply_glossary, load_glossary
from voice_paste.features.history import (
    append_text,
    discard_temporary,
    purge_expired,
    save_recording,
)
from voice_paste.features.outputs import (
    OUTPUTS,
    PRESET_KINDS,
    OutputDeps,
    OutputSpec,
    PresetKindSpec,
    deliver,
    is_callback_allowed,
)
from voice_paste.features.outputs.paste_and_send import read_enter_delay_sec
from voice_paste.features.recording import Recorder
from voice_paste.features.recording.client import open_input
from voice_paste.features.session import (
    Session,
    SessionApiDeps,
    SessionDeps,
    SessionManager,
)
from voice_paste.features.session.types import NotifyFn, SessionState
from voice_paste.features.transcription.service import transcribe
from voice_paste.integrations.browser.opener import open_app_window
from voice_paste.integrations.http.client import post_json
from voice_paste.integrations.keyboard.sender import copy_to_clipboard, send_enter, send_paste
from voice_paste.integrations.vad.adapter import StreamingVad, load_vad_session
from voice_paste.integrations.volume.adapter import lower_volume, restore_volume
from voice_paste.integrations.whisper.client import WhisperWorkerClient
from voice_paste.runtime.hotkey import HotkeyListener, validate_hotkeys
from voice_paste.runtime.process import relaunch
from voice_paste.runtime.settings_store import SettingsStore
from voice_paste.runtime.single_instance import (
    SingleInstanceLock,
    acquire_single_instance,
    instance_name,
)
from voice_paste.runtime.timer import RepeatingTimer
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token, write_token_file
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.errors import (
    EngineError,
    HotkeyError,
    MicrophoneUnavailableError,
    SessionBusyError,
    SettingsError,
    StartupError,
)
from voice_paste.shared.logger import local_today, purge_old_logs, setup_logging
from voice_paste.shared.settings import (
    Preset,
    Settings,
    build_settings_model,
    load_settings,
    save_settings,
)
from voice_paste.shared.types import Entry, ProgressFn, TranscriptionOutcome
from voice_paste.ui.bridge import UiBridge, notify, report_progress
from voice_paste.ui.controller import UiController, UiDeps
from voice_paste.ui.style import apply_theme
from voice_paste.ui.tray import Tray, TrayState
from voice_paste.ui.windows.recording_window import RecordingWindow
from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

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

WORKER_READY_TIMEOUT_SEC: float = 27.0
"""文字起こしワーカーの立て直しで ready を待つ上限。非機能要件の文字起こしワーカーの立て直しの時間の決定値。"""

WORKER_STOP_TIMEOUT_SEC: float = 2.0
"""文字起こしワーカーの終わりを待つ時間。非機能要件の文字起こしワーカーの終わりを待つ時間の決定値。"""

GLOSSARY_FILE_NAME: str = "yogo.csv"
"""用語集のパスを設定しないときに、設定ファイルと同じフォルダから読む用語集の名前。"""

ACCEPT_INJECTED_HOTKEYS_ENV: str = "VOICE_PASTE_ACCEPT_INJECTED_HOTKEYS"
"""`1` のときだけ、ソフトウェアで送ったキーもホットキーとして受ける環境変数（E2E の起動で付ける）。"""

WAKE_INTERVAL_MS: int = 200
"""Qt のイベントループの中で Python のシグナルのハンドラが動くようにする、空の QTimer の間隔。PoC で 200 ms なら Ctrl+Break から 0.3 秒で終わった。"""

SINGLE_INSTANCE_TIMEOUT_SEC: float = 54.0
"""acquire_single_instance に渡す、前のプロセスが排他を放すのを待つ上限。非機能要件の前の常駐サービスの終わりを待つ時間の決定値。"""

SETTINGS_MODEL: type[Settings] = build_settings_model(
    [spec.settings_model for spec in OUTPUTS if spec.settings_model is not None]
)
"""アプリの設定のモデル。OUTPUTS の設定のモデルを OUTPUTS の並びで組み立てたもので、設定の読み込みと既定の設定はこれを使う。"""

PURGE_INTERVAL_SEC: float = 86400.0
"""RepeatingTimer が purge_old_files を呼ぶ間隔。非機能要件の常駐中に古い履歴とログを消す間隔（24 時間）を秒にした値。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CliArgs:
    """`python -m voice_paste` に渡した引数。"""

    data_dir: Path | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Handlers:
    """入口（API・ホットキー・画面）が使う配線済みのもの。"""

    session_manager: SessionManager
    """セッション管理。"""

    session_api: SessionApiDeps
    """API サーバーへ渡すセッションの API の依存（設定の許可ホストを部分適用した返送先の確かめを含む）。"""

    settings_store: SettingsStore
    """今効いている設定。出力先・録音・画面はここから読むため、保存した immediate の項目が次の回から効く。"""

    start_local_session: Callable[[Entry], None]
    """ホットキー・トレイの開始（SessionManager と notify を部分適用した start_local_session）。"""

    recorder_level: Callable[[], float]
    """録音中の音量（Recorder.level）。録音の画面の波形に使う。"""

    stop_engine: Callable[[], None]
    """文字起こしのエンジンを止める。終了時に呼ぶ。"""


def parse_args(argv: list[str]) -> CliArgs:
    """argparse で `--data-dir` を読む。"""
    parser = argparse.ArgumentParser(prog="voice_paste")
    # 置き場所が無ければ既定の置き場所を使う（E2E・非機能要件テストは一時フォルダを渡して普段使いに触れない）
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="設定・履歴・ログ・一時の音声・トークンを置くフォルダ（無ければ既定の置き場所）",
    )
    namespace = parser.parse_args(argv)
    return CliArgs(data_dir=namespace.data_dir)


def _purge_while_running(
    settings_store: SettingsStore, session_manager: SessionManager, paths: AppPaths
) -> None:
    """常駐中の定期の削除。今の設定と、処理中のセッションの ID（一時の音声を残す）を引いて purge_old_files を呼ぶ。"""

    def _active_session_ids() -> set[str]:
        """処理中のセッションの ID を返す（待機中は空）。"""
        current = session_manager.current()
        return set() if current is None else {current.id}

    purge_old_files(settings_store.get(), paths=paths, active_session_ids=_active_session_ids)


def _local_now() -> datetime:
    """今の時刻を、この端末のタイムゾーンつきで返す。"""
    return datetime.now(UTC).astimezone()


def purge_old_files(
    settings: Settings,
    *,
    paths: AppPaths,
    active_session_ids: Callable[[], set[str]],
) -> None:
    """設定の保持期間を過ぎたログと履歴を消す。"""
    # 1. 保持期間を過ぎた日付のログを消す
    purge_old_logs(paths.log_dir, settings.logging.retention_days, local_today())

    # 2. 履歴を残す設定か
    if settings.history.enabled:
        # 残す: 保持期間を過ぎた履歴のフォルダと、取り残された一時の音声を消す
        purge_expired(
            retention_days=settings.history.retention_days,
            paths=paths,
            now=_local_now,
            active_session_ids=active_session_ids,
        )
    # 残さない: 履歴は消さない


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
    preset_kinds: tuple[PresetKindSpec, ...],
) -> None:
    """Session を入口・選んだ出力先・選んだプリセット・返送先に分けて、出力先の deliver へ渡す（出力先はセッションを import しない）。"""
    deliver(
        session.entry,
        session.output_id,
        session.output_preset,
        session.callback_url,
        outcome,
        enabled_ids=enabled_ids,
        outputs=outputs,
        preset_kinds=preset_kinds,
    )


def _make_paste(get_settings: Callable[[], Settings]) -> Callable[[], None]:
    """呼ぶたびに設定の貼り付けのキーで貼り付けのキーを送る関数を作る。"""

    def paste() -> None:
        """設定の貼り付けのキーで貼り付けのキーを送る。"""
        send_paste(get_settings().keyboard.paste_key)

    return paste


def _wire_outputs(deps: OutputDeps, outputs: Sequence[OutputSpec]) -> tuple[OutputSpec, ...]:
    """各出力先の handler に、その出力先の inject が OutputDeps から選んだものを部分適用して返す（出力先の ID ごとの表は持たない）。"""
    wired: list[OutputSpec] = []
    for spec in outputs:
        injected = spec.inject(deps)
        # 注入するものがある出力先だけ handler を差し替える（無い出力先はそのまま残す）
        wired.append(replace(spec, handler=partial(spec.handler, **injected)) if injected else spec)
    return tuple(wired)


def _wire_preset_kinds(get_settings: Callable[[], Settings]) -> tuple[PresetKindSpec, ...]:
    """プリセットの種類の一覧の各 handler に、種類ごとの外部連携の関数と設定の値を部分適用して返す。"""
    # 1. 届けるたびに設定を読む関数を作る
    paste = _make_paste(get_settings)

    def get_enter_delay_sec() -> float:
        """設定の貼り付けて送信の、貼り付けてから Enter を送るまでの秒数を返す。"""
        return read_enter_delay_sec(get_settings())

    def get_open_delay_sec() -> float:
        """設定のブラウザ添付の、画面を開いてから貼り付けるまでの秒数を返す。"""
        return get_settings().preset_options.browser.open_delay_sec

    def get_timeout_sec() -> float:
        """設定のエンドポイントへ送るの、送るときのタイムアウトの秒数を返す。"""
        return get_settings().preset_options.endpoint.timeout_sec

    # 2. 種類ごとに、handler へ注入するものを決める
    injections: dict[str, dict[str, object]] = {
        "browser": {
            "copy": copy_to_clipboard,
            "open_window": open_app_window,
            "paste": paste,
            "send_enter": send_enter,
            "sleep": time.sleep,
            "get_open_delay_sec": get_open_delay_sec,
            # 貼り付けて送信と同じ間を使う
            "get_enter_delay_sec": get_enter_delay_sec,
        },
        "endpoint": {"post": post_json, "get_timeout_sec": get_timeout_sec},
    }

    # 3. 一覧の順のまま、注入するものがある種類だけ handler を差し替える（無い種類はそのまま残す）
    return tuple(
        replace(spec, handler=partial(spec.handler, **injections[spec.kind]))
        if spec.kind in injections
        else spec
        for spec in PRESET_KINDS
    )


def _glossary_path(settings: Settings, paths: AppPaths) -> Path:
    """設定の用語集の CSV を返す（設定していなければ、設定ファイルと同じフォルダの用語集）。"""
    return settings.glossary_path or paths.settings_file.parent / GLOSSARY_FILE_NAME


def build_handlers(
    settings: Settings, paths: AppPaths, notify: NotifyFn, report_progress: ProgressFn
) -> Handlers:
    """設定からエンジン・録音機・出力先・履歴を組み立て、SessionDeps を作って SessionManager と SessionApiDeps を返す。"""
    # 1. 設定を SettingsStore に入れる。以降の配線は設定を値でなく SettingsStore.get から読む
    store = SettingsStore(settings)

    # 2. 設定のエンジン（local_whisper）のワーカーを作って起動する
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

    # 3. 連続録音の話し声の判定に使う VAD のセッションを 1 回だけ読む（読めなければ立ち上げたエンジンを止めて起動の失敗にする）
    try:
        vad_session = load_vad_session()
    except StartupError:
        engine.stop()
        raise

    # 4. 録音機に音量とマイクの入力の関数と、SettingsStore から録音の設定を返す関数と、VAD のセッションを部分適用した話し声の判定を作る関数を渡す
    recorder = Recorder(
        lower_volume=lower_volume,
        restore_volume=restore_volume,
        open_input=open_input,
        get_settings=lambda: store.get().recording,
        create_speech_detector=partial(StreamingVad, vad_session),
    )

    # 5. 出力先とプリセットの種類を配線し、届けるたびに SettingsStore からオンの出力先の ID を引いて、Session を分けて渡すアダプタを作る
    output_deps = OutputDeps(
        copy=copy_to_clipboard,
        paste=_make_paste(store.get),
        send_enter=send_enter,
        sleep=time.sleep,
        jitter=_jitter,
        post=post_json,
        get_settings=store.get,
    )
    wired_outputs = _wire_outputs(output_deps, OUTPUTS)
    wired_preset_kinds = _wire_preset_kinds(store.get)

    def deliver_session(session: Session, outcome: TranscriptionOutcome) -> None:
        """今の設定でオンの出力先へ、Session を分けて届ける。"""
        enabled_ids = frozenset(output.id for output in store.get().outputs if output.enabled)
        _deliver_session(
            session,
            outcome,
            enabled_ids=enabled_ids,
            outputs=wired_outputs,
            preset_kinds=wired_preset_kinds,
        )

    # 6. 用語集を文字起こしのたびに読み直す補正を作る（読む場所もそのたびに設定から決める）
    def correct(text: str) -> str:
        """今の設定の用語集で補正する。"""
        return _correct(text, glossary_path=_glossary_path(store.get(), paths))

    # 7. SessionDeps を組み、API のセッションの上限時間と連続録音の上限時間（起動時の設定。再起動で効く）と共に SessionManager を作る
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
        correct=correct,
        append_text=partial(append_text, paths=paths),
        deliver=deliver_session,
        notify=notify,
        now=_local_now,
        discard_temporary=partial(discard_temporary, paths=paths),
        report_progress=report_progress,
        start_continuous_recording=partial(
            recorder.start_continuous,
            min_silence_sec=settings.api.continuous.min_silence_sec,
        ),
        stop_continuous_recording=recorder.stop_continuous,
    )
    session_manager = SessionManager(
        deps,
        timedelta(seconds=API_SESSION_LIMIT_SEC),
        timedelta(seconds=settings.api.continuous.session_limit_sec),
    )

    # 8. SessionManager と、設定の許可ホストを部分適用した返送先の確かめを SessionApiDeps に束ねる
    session_api = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=partial(
            is_callback_allowed, allowed_hosts=frozenset(settings.api.allowed_callback_hosts)
        ),
    )

    # 9. start_local_session に SessionManager と notify を部分適用する
    return Handlers(
        session_manager=session_manager,
        session_api=session_api,
        settings_store=store,
        start_local_session=partial(
            start_local_session, session_manager=session_manager, notify=notify
        ),
        recorder_level=recorder.level,
        stop_engine=engine.stop,
    )


def start_local_session(
    entry: Entry | str, *, session_manager: SessionManager, notify: NotifyFn
) -> None:
    """SessionManager.start を呼び、断られた理由をユーザーへ知らせる。例外を pynput・画面のスレッドへ漏らさない。"""
    try:
        session_manager.start(entry)
    except SessionBusyError:
        # 処理中: 処理中のダイアログで知らせる
        notify("busy", None)
    except MicrophoneUnavailableError:
        # マイクを開けない: トレイの通知で知らせる
        notify("microphone_unavailable", None)
    except Exception:  # noqa: BLE001 pynput・画面のスレッドへ例外を漏らさないため
        logger.exception("録音を始められなかった")


def _collect_hotkeys(settings: Settings) -> list[str]:
    """設定で受け付けるホットキー（録音・一時停止・取り消し・オンの出力先・有効なプリセット）を、重なりを除いて並べる。"""
    hotkeys = [settings.hotkeys.start, settings.hotkeys.pause, settings.hotkeys.cancel]
    hotkeys.extend(output.hotkey for output in settings.outputs if output.enabled)
    hotkeys.extend(preset.hotkey for preset in settings.presets if preset.enabled)
    # 空のホットキーは登録しない。重なり（録音の開始と貼り付けて送信）は 1 つにする
    return list(dict.fromkeys(hotkey for hotkey in hotkeys if hotkey))


def build_hotkey_bindings(
    settings: Settings,
    session_manager: SessionManager,
    start_local_session: Callable[[Entry], None],
    show_recording_window: Callable[[], None],
) -> dict[str, Callable[[], None]]:
    """設定のホットキーごとに、押されたときに呼ぶ関数を組む（HotkeyListener.start へ渡す）。"""
    start_hotkey = settings.hotkeys.start
    # 録音開始のホットキーと同じキーを持つ、オンの出力先（録音中に押すとその出力先で確定する）
    confirm_output_id = next(
        (
            output.id
            for output in settings.outputs
            if output.enabled and output.hotkey.lower() == start_hotkey.lower()
        ),
        None,
    )

    def on_start() -> None:
        """ホットキー・トレイの録音中なら出力先で確定し（出力先が無ければ隠した録音の画面を戻す指示を出す）、そうでなければ録音を始める。"""
        session = session_manager.current()
        is_local_recording = (
            session is not None
            and session.entry != Entry.API
            and session.state in (SessionState.RECORDING, SessionState.PAUSED)
        )
        # 自分の録音の最中: 同じホットキーの出力先があればそれで確定し、無ければ隠した録音の画面を戻す指示を出す（処理中のダイアログを出さない。隠していなければ UiController が何もしない）
        if is_local_recording:
            if confirm_output_id is not None:
                session_manager.complete(output_id=confirm_output_id)
            else:
                show_recording_window()
            return
        start_local_session(Entry.HOTKEY)

    def on_pause() -> None:
        """一時停止中なら再開し、そうでなければ一時停止する。"""
        session = session_manager.current()
        if session is not None and session.state == SessionState.PAUSED:
            session_manager.resume()
        else:
            session_manager.pause()

    bindings: dict[str, Callable[[], None]] = {
        start_hotkey: on_start,
        settings.hotkeys.pause: on_pause,
        settings.hotkeys.cancel: session_manager.cancel,
    }
    for output in settings.outputs:
        # オンの出力先のホットキー（録音開始と同じキーを除く）: その出力先で確定する
        if output.enabled and output.hotkey.lower() != start_hotkey.lower():
            bindings[output.hotkey] = partial(session_manager.complete, output_id=output.id)
    for preset in settings.presets:
        # 有効なプリセットのホットキー: そのプリセットで確定する
        if preset.enabled:
            bindings[preset.hotkey] = partial(session_manager.complete, preset=preset)
    # 空のホットキーは登録しない（重なりは Settings の確かめが断っている）
    return {hotkey: handler for hotkey, handler in bindings.items() if hotkey}


def apply_settings(
    settings: Settings,
    *,
    settings_file: Path,
    store: SettingsStore,
    check_hotkeys: Callable[[Iterable[str]], None],
) -> bool:
    """設定画面で確かめた設定を settings.toml へ書き、反映が immediate の項目を動いている常駐アプリに効かせる。

    新しい設定のホットキーを pynput が読めなければ、何も書かず入れ替えずに HotkeyError を送出する。
    """
    # 1. 新しい設定で受け付けるホットキーを確かめる
    check_hotkeys(_collect_hotkeys(settings))

    # 2. settings.toml へ書く（書けなければ OSError のまま伝え、SettingsStore は入れ替えない）
    restart_needed = save_settings(settings_file, settings)

    # 3. SettingsStore を入れ替える（ホットキーは設定画面が閉じたときに今の設定で張り直す）
    store.replace(settings)
    logger.info(f"設定を保存した（{settings_file}・再起動が要る: {restart_needed}）")
    return restart_needed


def _output_titles() -> dict[str, str]:
    """画面に出す出力先の名前（出力先の ID → 名前。API 専用の出力先を除く）を返す。"""
    return {spec.id: spec.title for spec in OUTPUTS if not spec.api_only}


def build_ui_deps(
    handlers: Handlers,
    paths: AppPaths,
    save_settings: Callable[[Settings], bool],
    request_restart: Callable[[], None],
    request_quit: Callable[[], None],
    hotkey_listener: HotkeyListener,
    show_recording_window: Callable[[], None],
    apply_theme: Callable[[], None],
) -> UiDeps:
    """Handlers と置き場所から、画面・トレイが呼ぶ UiDeps を組む。"""
    session_manager = handlers.session_manager
    store = handlers.settings_store

    def complete(output_id: str | None, preset: Preset | None) -> None:
        """固定の出力先の ID かカスタムプリセットで録音を確定する。"""
        session_manager.complete(output_id=output_id, preset=preset)

    def resume_hotkeys() -> None:
        """今の設定でホットキーの受付を始める。"""
        bindings = build_hotkey_bindings(
            store.get(), session_manager, handlers.start_local_session, show_recording_window
        )
        hotkey_listener.start(bindings)

    return UiDeps(
        start=partial(handlers.start_local_session, Entry.TRAY),
        pause=session_manager.pause,
        resume=session_manager.resume,
        complete=complete,
        cancel=session_manager.cancel,
        current_session=session_manager.current,
        level=handlers.recorder_level,
        get_settings=store.get,
        save_settings=save_settings,
        settings_dir=paths.settings_file.parent,
        log_dir=paths.log_dir,
        request_restart=request_restart,
        request_quit=request_quit,
        suspend_hotkeys=hotkey_listener.stop,
        resume_hotkeys=resume_hotkeys,
        output_titles=_output_titles(),
        apply_theme=apply_theme,
    )


def _apply_current_theme(app: QApplication, get_settings: Callable[[], Settings]) -> None:
    """今の設定の ui.theme で画面の明暗を当て直す。"""
    apply_theme(app, get_settings().ui.theme)


def _watch_system_theme(app: QApplication, reapply: Callable[[], None]) -> None:
    """OS の明暗が変わったときに、画面の明暗を当て直す（ui.theme が system のときに配色が替わる）。"""
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: reapply())


def _build_idle_ui_deps(
    settings: Settings,
    paths: AppPaths,
    app: QApplication,
    request_restart: Callable[[], None],
    request_quit: Callable[[], None],
) -> UiDeps:
    """エンジンを準備できなかった起動の UiDeps を組む。録音・ホットキーの関数は何もせず、設定画面は読んだ設定で保存だけ行う。"""
    store = SettingsStore(settings)

    def do_nothing(*_args: object) -> None:
        """録音・ホットキーの関数の代わりに、何もしない。"""

    return UiDeps(
        start=do_nothing,
        pause=do_nothing,
        resume=do_nothing,
        complete=do_nothing,
        cancel=do_nothing,
        current_session=lambda: None,
        level=lambda: 0.0,
        get_settings=store.get,
        save_settings=partial(
            apply_settings,
            settings_file=paths.settings_file,
            store=store,
            check_hotkeys=validate_hotkeys,
        ),
        settings_dir=paths.settings_file.parent,
        log_dir=paths.log_dir,
        request_restart=request_restart,
        request_quit=request_quit,
        suspend_hotkeys=do_nothing,
        resume_hotkeys=do_nothing,
        output_titles=_output_titles(),
        apply_theme=partial(_apply_current_theme, app, store.get),
    )


class _ExitRequest:
    """イベントループを抜ける依頼と、抜けた後に起動し直すかを持つ（長く持つ実行時の状態）。"""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self.restart = False

    def request_restart(self) -> None:
        """終わった後に起動し直すようにして、イベントループを抜ける。"""
        self.restart = True
        self._app.quit()

    def request_quit(self) -> None:
        """イベントループを抜ける。"""
        self._app.quit()


@dataclass
class _Running:
    """片付けで止める、立てたもの（7 までで立てたものだけが入る）。"""

    handlers: Handlers | None = None
    runner: ApiServerRunner | None = None
    timers: list[RepeatingTimer] = field(default_factory=list)
    """上限の打ち切りと古い履歴・ログの削除の定期の呼び出し（立てた順）。"""
    hotkey_listener: HotkeyListener | None = None
    controller: UiController | None = None
    """画面の振り分け。Qt の部品は参照が切れると消えるため、終わりまで持つ。"""


def _stop_all(running: _Running, tray: Tray) -> None:
    """新しい開始が来ないように入口とタイマーを先に止め、録音を捨て、エンジンを止め、トレイを消す。"""
    if running.hotkey_listener is not None:
        running.hotkey_listener.stop()
    for timer in running.timers:
        timer.stop()
    if running.runner is not None:
        running.runner.stop()
    if running.handlers is not None:
        running.handlers.session_manager.close()
        running.handlers.stop_engine()
    tray.hide()


def _create_application() -> QApplication:
    """QApplication（最後の窓を閉じても終わらない）を作る。既にあればそれを使う。"""
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    return app


def _install_signal_handlers(app: QApplication) -> QTimer:
    """SIGINT・SIGBREAK で QApplication.quit を呼ぶ。イベントループの中で Python へ戻る空のタイマーを返す。"""
    wake_timer = QTimer(app)
    wake_timer.timeout.connect(lambda: None)
    wake_timer.start(WAKE_INTERVAL_MS)
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signal.signal(sigbreak, lambda *_args: app.quit())
    return wake_timer


def _run_event_loop(app: QApplication) -> int:
    """イベントループを回す。"""
    return app.exec()


def main(
    argv: list[str] | None = None,
    *,
    exec_loop: Callable[[QApplication], int] = _run_event_loop,
) -> int:
    """常駐サービスを起動し、イベントループが終わるまで回して片付け、終了コードを返す。"""
    # 1. 起動の引数を読む
    argv_used = sys.argv[1:] if argv is None else argv
    args = parse_args(argv_used)

    # 2. 置き場所を決め、ログを設定する
    paths = resolve_app_paths(args.data_dir)
    setup_logging(paths.log_dir, STARTUP_LOG_LEVEL)

    # 3. 置き場所ごとの名前で単一インスタンスを確保する（前のプロセスが動いていれば、終わるよう頼んで放されるのを待つ）
    try:
        lock = acquire_single_instance(
            instance_name(paths.settings_file.parent), SINGLE_INSTANCE_TIMEOUT_SEC
        )
    except StartupError as error:
        # トレイを出す前のため、ログにだけ残して終わる
        logger.error(f"起動に失敗した（{error}）")
        return EXIT_FAILED

    # 4〜11. 排他を持ったまま起動して回し、どう抜けても最後に排他を放す
    try:
        exit_code, restart = _run_service(paths, lock, exec_loop)
    finally:
        lock.release()

    # 12. 再起動を頼まれていれば、同じ引数で起動し直す（排他を放した後のため、次のプロセスは待たずに取れる）
    if restart:
        relaunch(argv_used)
    return exit_code


def _run_service(
    paths: AppPaths,
    lock: SingleInstanceLock,
    exec_loop: Callable[[QApplication], int],
) -> tuple[int, bool]:
    """排他を持った状態で、画面の用意・起動・イベントループ・片付けを行い、終了コードと再起動の要否を返す。"""
    # 5. QApplication・UiBridge・Tray を作り、スタイルを当ててトレイに準備中を出す
    app = _create_application()
    # 後から起動したプロセスに終わるよう頼まれたら、メインスレッドで QApplication.quit を呼ぶ
    lock.on_quit_requested(
        lambda: QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)
    )
    bridge = UiBridge()
    tray = Tray(paths.settings_file.parent, paths.log_dir)
    apply_theme(app, "system")
    tray.set_state(TrayState.STARTING, busy=False)
    wake_timer = _install_signal_handlers(app)
    exit_request = _ExitRequest(app)
    running = _Running()

    try:
        _start_services(app, bridge, tray, paths, exit_request, running)
        # 12. イベントループを回す
        exec_loop(app)
    finally:
        # 13. 立てたものを止める
        wake_timer.stop()
        _stop_all(running, tray)
        logger.info("常駐サービスを終えた")
    return EXIT_OK, exit_request.restart


def _start_services(
    app: QApplication,
    bridge: UiBridge,
    tray: Tray,
    paths: AppPaths,
    exit_request: _ExitRequest,
    running: _Running,
) -> None:
    """設定を読み、配線し、画面・API・ホットキー・上限のタイマーを立てる。立てたものは running に入れる。"""
    ui_notify = partial(notify, bridge=bridge)
    ui_report_progress = partial(report_progress, bridge=bridge)
    show_recording_window = partial(notify, "show_recording_window", bridge=bridge)

    # 5. 設定を読む（読めなければトレイを失敗にして知らせ、設定を直して再起動できるようにする）
    try:
        settings = load_settings(paths.settings_file, SETTINGS_MODEL)
    except SettingsError as error:
        logger.error(f"起動に失敗した（{error}）")
        tray.set_failed()
        tray.show_failure("settings_invalid", str(error))
        tray.restart_requested.connect(exit_request.request_restart)
        tray.quit_requested.connect(exit_request.request_quit)
        return

    # 6. 設定の ui.theme で画面の明暗を当て直し、ルートロガーのレベルを設定のログのレベルにし、保持期間で古いログと履歴を消す（処理中のセッションは無いため、一時の音声も全て消す対象にする）
    apply_theme(app, settings.ui.theme)
    logging.getLogger().setLevel(settings.logging.level)
    purge_old_files(settings, paths=paths, active_session_ids=set)
    enabled_outputs = [output.id for output in settings.outputs if output.enabled]
    logger.info(
        f"設定を読んだ（{paths.settings_file}、エンジン: {settings.transcription.engine}、"
        f"オンの出力先: {', '.join(enabled_outputs)}）"
    )

    # 7. 配線する（エンジンを準備できなければトレイを失敗にして知らせ、設定画面だけを使えるようにする）
    try:
        handlers = build_handlers(settings, paths, ui_notify, ui_report_progress)
    except StartupError as error:
        logger.error(f"起動に失敗した（{error}）")
        tray.set_failed()
        deps = _build_idle_ui_deps(
            settings, paths, app, exit_request.request_restart, exit_request.request_quit
        )
        _watch_system_theme(app, deps.apply_theme)
        running.controller = _build_controller(bridge, tray, deps)
        tray.show_failure("engine_unavailable", str(error))
        return
    running.handlers = handlers

    # 画面を作って知らせの受け手につなぐ（API の待ち受けを始められない知らせを取りこぼさないよう、API より先に）
    accept_injected = os.environ.get(ACCEPT_INJECTED_HOTKEYS_ENV) == "1"
    if accept_injected:
        logger.info("ソフトウェアで送ったキーもホットキーとして受ける")
    hotkey_listener = HotkeyListener(accept_injected=accept_injected)
    running.hotkey_listener = hotkey_listener
    save_settings_fn = partial(
        apply_settings,
        settings_file=paths.settings_file,
        store=handlers.settings_store,
        check_hotkeys=validate_hotkeys,
    )
    deps = build_ui_deps(
        handlers,
        paths,
        save_settings_fn,
        exit_request.request_restart,
        exit_request.request_quit,
        hotkey_listener,
        show_recording_window,
        partial(_apply_current_theme, app, handlers.settings_store.get),
    )
    _watch_system_theme(app, deps.apply_theme)
    running.controller = _build_controller(bridge, tray, deps)

    # 8. トークンを作り、API サーバーを起動する
    token = create_token()
    port = settings.api.port
    runner = ApiServerRunner(build_fastapi(handlers.session_api, token, port), port)
    if runner.start(API_START_TIMEOUT_SEC):
        running.runner = runner
        write_token_file(paths.token_file, port, token)
    else:
        # 待ち受けを始められなかった: トークンのファイルは書かず（ほかの起動のトークンを上書きしない）、知らせて続ける
        ui_notify("api_unavailable", f"ポート {port} で待ち受けを始められません")

    # 9. ホットキーの受付と上限の打ち切りのタイマーを始め、トレイを待機中にする
    try:
        hotkey_listener.start(
            build_hotkey_bindings(
                handlers.settings_store.get(),
                handlers.session_manager,
                handlers.start_local_session,
                show_recording_window,
            )
        )
    except HotkeyError as error:
        logger.error(f"ホットキーを受け付けられなかった（{error}）")
    limit_timer = RepeatingTimer(
        handlers.session_manager.truncate_if_expired, SESSION_LIMIT_CHECK_INTERVAL_SEC
    )
    limit_timer.start()
    running.timers.append(limit_timer)
    # 常駐中の古いログと履歴の削除（設定は呼ぶたびに引き、設定画面で変えた保持期間を次の回から効かせる）
    purge_timer = RepeatingTimer(
        partial(
            _purge_while_running,
            handlers.settings_store,
            handlers.session_manager,
            paths,
        ),
        PURGE_INTERVAL_SEC,
    )
    purge_timer.start()
    running.timers.append(purge_timer)
    tray.set_start_hotkey(settings.hotkeys.start)
    tray.set_state(TrayState.IDLE, busy=False)
    logger.info(f"常駐サービスを始めた（API のポート: {port}）")


def _build_controller(bridge: UiBridge, tray: Tray, deps: UiDeps) -> UiController:
    """録音の画面・文字起こし中の表示・UiController を作り、UiBridge の知らせの受け手につなぐ。"""
    controller = UiController(
        deps,
        tray=tray,
        recording_window=RecordingWindow(deps),
        indicator=TranscribingIndicator(deps),
    )
    bridge.notified.connect(controller.on_notified, Qt.ConnectionType.QueuedConnection)
    bridge.progressed.connect(controller.on_progressed, Qt.ConnectionType.QueuedConnection)
    tray.set_start_hotkey(deps.get_settings().hotkeys.start)
    return controller
