"""起動の入口。設定を読み、各 feature を関数で配線し（composition root）、API・ホットキー・トレイを立てて画面のイベントループを回す。"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from voice_paste.features.correction import (
    apply_glossary,
    list_preset_glossaries,
    load_glossary,
    next_glossary_path,
    pick_glossary_preset,
    read_glossary_rows,
    resolve_glossaries,
    resolve_glossary_presets,
    save_glossary,
    strip_edge_phrases,
)
from voice_paste.features.history import (
    append_text,
    discard_temporary,
    purge_expired,
    save_recording,
    store_web_audio,
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
from voice_paste.features.recording.types import LowerVolumeFn, RestoreVolumeFn
from voice_paste.features.session import (
    Session,
    SessionApiDeps,
    SessionDeps,
    SessionManager,
)
from voice_paste.features.session.types import NotifyFn, SessionState
from voice_paste.features.transcription import EngineFn, EngineName
from voice_paste.features.transcription.service import transcribe
from voice_paste.features.web_transcription import (
    GlossaryPresetChoices,
    WebApiDeps,
    WebJobQueue,
    WebTranscriptionDeps,
)
from voice_paste.integrations.audio.probe import probe_audio
from voice_paste.integrations.haas.server import HaasServer
from voice_paste.integrations.haas.transcriber import HaasTranscriber
from voice_paste.integrations.http.client import post_json
from voice_paste.integrations.keyboard.sender import copy_to_clipboard, send_enter, use_xclip_clipboard
from voice_paste.integrations.openai.credentials import read_openai_api_key
from voice_paste.integrations.openai.transcriber import OpenAITranscriber
from voice_paste.integrations.vad.adapter import StreamingVad, load_vad_session
from voice_paste.integrations.volume.noop import lower_volume_noop, restore_volume_noop
from voice_paste.integrations.whisper.client import (
    CREATE_NO_WINDOW,
    WhisperWorkerClient,
    ensure_local_whisper_installed,
)
from voice_paste.runtime.hotkey import HotkeyListener, validate_hotkeys
from voice_paste.runtime.process import relaunch
from voice_paste.runtime.settings_store import SettingsStore
from voice_paste.runtime.single_instance import SingleInstanceLock, instance_name
from voice_paste.runtime.timer import RepeatingTimer
from voice_paste.server.app import build_fastapi
from voice_paste.server.runner import ApiServerRunner
from voice_paste.server.token import create_token, write_token_file
from voice_paste.shared.constants import AppPaths, resolve_app_paths
from voice_paste.shared.errors import (
    DeliveryError,
    EngineError,
    HotkeyError,
    MicrophoneUnavailableError,
    SessionBusyError,
    SettingsError,
    StartupError,
)
from voice_paste.shared.logger import local_today, purge_old_logs, setup_logging
from voice_paste.shared.os_kind import (
    CURRENT_OS,
    DisplaySession,
    Feature,
    OsKind,
    detect_display_session,
    hidden_setting_keys,
    unavailable_features,
)
from voice_paste.shared.settings import (
    HaasSettings,
    HintVocabularyWord,
    Preset,
    Settings,
    build_settings_model,
    collect_hint_vocabulary,
    has_restart_change,
    join_hint_words,
    load_default_settings,
    load_settings,
    reset_settings,
    save_settings,
)
from voice_paste.shared.types import (
    Entry,
    GlossaryEntry,
    ProgressFn,
    SendEnterFn,
    TranscriptionOutcome,
)
from voice_paste.ui.bridge import UiBridge, notify, notify_copied, report_progress
from voice_paste.ui.controller import UiController, UiDeps
from voice_paste.ui.style import apply_theme
from voice_paste.ui.tray import Tray, TrayState
from voice_paste.ui.windows.recording_window import RecordingWindow
from voice_paste.ui.windows.transcribing_indicator import TranscribingIndicator

if TYPE_CHECKING:
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener
    from voice_paste.runtime.single_instance_linux import LinuxSingleInstanceLock

logger = logging.getLogger(__name__)

STARTUP_LOG_LEVEL: str = "INFO"
"""設定を読むまでのログのレベル。"""

EXIT_OK: int = 0
"""正常終了の終了コード。"""

EXIT_FAILED: int = 1
"""起動に失敗した終了コード。"""

QT_PLATFORM_ENV: str = "QT_QPA_PLATFORM"
"""Qt のプラットフォームを選ぶ環境変数。"""

QT_PLATFORM_XCB: str = "xcb"
"""Wayland のセッションで使う Qt のプラットフォーム（XWayland）。ネイティブの wayland では画面が設定の位置に置けず、貼り付け先のフォーカスを取る。"""

API_START_TIMEOUT_SEC: float = 5.0
"""ApiServerRunner.start が started を待つ上限。uvicorn の起動の実測が無いため仮に置く。"""

SESSION_LIMIT_CHECK_INTERVAL_SEC: float = 1.0
"""上限での打ち切りを確かめる間隔。打ち切りの遅れはこの間隔までで、上限時間に対して無視できる。"""

API_SESSION_LIMIT_SEC: int = 600
"""API の録音セッションの上限時間。非機能要件の API の録音セッションの上限時間の決定値。"""

WORKER_READY_TIMEOUT_SEC: float = 27.0
"""文字起こしワーカーの立て直しで ready を待つ上限。非機能要件の文字起こしワーカーの立て直しの時間の決定値。"""

WORKER_STOP_TIMEOUT_SEC: float = 2.0
"""文字起こしワーカーの終わりを待つ時間。非機能要件の文字起こしワーカーの終わりを待つ時間の決定値。"""

GLOSSARIES_DIR_NAME: str = "glossaries"
"""設定画面で追加した用語集の CSV を置く、settings.yaml と同じフォルダの下のフォルダの名前。"""

WAKE_INTERVAL_MS: int = 200
"""Qt のイベントループの中で Python のシグナルのハンドラが動くようにする、空の QTimer の間隔。PoC で 200 ms なら Ctrl+Break から 0.3 秒で終わった。"""

SINGLE_INSTANCE_TIMEOUT_SEC: float = 55.0
"""acquire_single_instance に渡す、前のプロセスが排他を放すのを待つ上限。非機能要件の前の常駐サービスの終わりを待つ時間の決定値。"""

SETTINGS_MODEL: type[Settings] = build_settings_model(
    [spec.settings_model for spec in OUTPUTS if spec.settings_model is not None]
)
"""アプリの設定のモデル。OUTPUTS の設定のモデルを OUTPUTS の並びで組み立てたもので、設定の読み込みと既定の設定はこれを使う。"""

WEB_TMP_DIR_NAME: str = "web"
"""ブラウザから受けた音声を書く一時のフォルダの名前（`{tmp_dir}` の下）。"""

STARTUP_CANCEL_TIMEOUT_SEC: float = 5.0
"""配線の間に抜けたときに、配線のスレッドの終わりを待つ秒数。ワーカーの終わりを WORKER_STOP_TIMEOUT_SEC の 2 回待ってから kill するまでに、配線が StartupError で終わる余裕の 1 秒を加えた値。"""

STARTUP_THREAD_NAME: str = "startup-build"
"""配線を流すスレッドの名前。"""

PURGE_INTERVAL_SEC: float = 86400.0
"""RepeatingTimer が purge_old_files を呼ぶ間隔。非機能要件の常駐中に古い履歴とログを削除する間隔（24 時間）を秒にした値。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CliArgs:
    """`python -m voice_paste` に渡した引数。"""

    data_dir: Path | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformAdapters:
    """動いている OS とデスクトップのセッションに合わせて選んだ、単一インスタンス・音量・ブラウザ・貼り付けのキーと Enter の送信・ホットキーの受付・Qt のプラットフォーム・文字起こしワーカーの起動・再起動の実装。

    select_platform_adapters が作る。OS を見て実装を選ぶのはここだけで、各モジュールは sys.platform を見ない。
    """

    acquire_single_instance: Callable[[str, float], SingleInstanceLock | LinuxSingleInstanceLock]
    """単一インスタンスの確保（名前・待つ上限）。"""

    lower_volume: LowerVolumeFn | None
    """録音中に音量を下げる（Windows）。Linux は None（build_handlers が OS_UNAVAILABLE_FEATURES の Feature.LOWER_VOLUME を見て、何もしない関数を渡す）。"""

    restore_volume: RestoreVolumeFn | None
    """下げた音量を戻す（Windows）。Linux は None。"""

    open_app_window: Callable[[str], None]
    """ブラウザ添付のプリセットの画面を開く。"""

    worker_creationflags: int
    """文字起こしワーカーの子プロセスの起動のフラグ（WhisperWorkerClient へ渡す）。"""

    relaunch: Callable[[list[str]], None]
    """同じ引数で起動し直す（os_kind を部分適用した relaunch）。"""

    send_paste: Callable[[str], None]
    """貼り付けのキーの送信（設定の keyboard.paste_key を受ける。Windows は send_paste、Linux の Xorg のセッションは send_paste_linux、Wayland のセッションは UInputKeyboard.send_paste）。"""

    send_enter: SendEnterFn
    """Enter の送信（Windows と Linux の Xorg のセッションは send_enter、Wayland のセッションは UInputKeyboard.send_enter）。"""

    create_hotkey_listener: Callable[
        [str, SingleInstanceLock | LinuxSingleInstanceLock], HotkeyListener | GnomeShortcutListener
    ]
    """ホットキーの受付を作る（排他の名前・取った排他を受ける。Windows と Linux の Xorg のセッションは引数を使わず HotkeyListener()、Wayland のセッションは GnomeShortcutListener）。"""

    qt_platform: str | None
    """Qt のプラットフォーム（main が QT_QPA_PLATFORM に入れる）。Wayland のセッションは `xcb`（XWayland）、ほかは None（Qt に任せる）。"""

    open_key_sender: Callable[[], None]
    """キーの送信の機器を開く（Wayland のセッションは UInputKeyboard.open。開けなければ DeliveryError を送出する）。ほかは何もしない関数。"""

    close_key_sender: Callable[[], None]
    """キーの送信の機器を閉じる（Wayland のセッションは UInputKeyboard.close）。ほかは何もしない関数。"""

    validate_hotkeys: Callable[[Iterable[str]], None]
    """設定の保存の前に、ホットキーを動いているセッションの受付で受け付けられるかを確かめる（Windows と Linux の Xorg のセッションは validate_hotkeys、Wayland のセッションは validate_gnome_hotkeys）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Handlers:
    """入口（API・ホットキー・画面）が使う配線済みのもの。"""

    session_manager: SessionManager
    """録音セッション管理。"""

    session_api: SessionApiDeps
    """API サーバーへ渡す録音セッションの API の依存（設定の許可ホストを部分適用したコールバック先の確かめを含む）。"""

    web_api: WebApiDeps | None
    """API サーバーへ渡すブラウザの API の依存（WebJobQueue・probe_audio・一時のフォルダ）。WebJobQueue の開始と終了は main が呼ぶ。外の端末のブラウザの機能を使えない OS では None。"""

    settings_store: SettingsStore
    """今効いている設定。出力先・録音・画面はここから読むため、保存した immediate の項目が次の回から効く。"""

    start_local_session: Callable[[Entry], None]
    """ホットキー・トレイの開始（SessionManager と notify を部分適用した start_local_session）。"""

    recorder_level: Callable[[], float]
    """録音中の音量（Recorder.level）。録音の画面の波形に使う。"""

    stop_engine: Callable[[], None]
    """文字起こしのエンジンを止める。終了時に呼ぶ。"""

    active_engine: EngineName
    """実際に動いているエンジン。設定が haas で切り戻した起動では local_whisper。"""


def _do_nothing() -> None:
    """キーの送信の機器を開く・閉じる必要が無い OS・セッションで、開く・閉じるの代わりに何もしない。"""


def select_platform_adapters(
    os_kind: OsKind, *, lock_file: Path, display_session: DisplaySession
) -> PlatformAdapters:
    """OS とデスクトップのセッションに合った実装を PlatformAdapters に束ねる。その OS・セッションだけのモジュールは、選んだ分岐の中で import する。"""
    # OS で分ける
    if os_kind is OsKind.WINDOWS:
        # Windows: pycaw の音量・Edge・Win32 の排他（comtypes・pycaw を読み込むため Linux では import しない）
        from voice_paste.integrations.browser.opener import open_app_window
        from voice_paste.integrations.keyboard.sender import send_paste
        from voice_paste.integrations.volume.adapter import lower_volume, restore_volume
        from voice_paste.runtime.single_instance import acquire_single_instance

        return PlatformAdapters(
            acquire_single_instance=acquire_single_instance,
            lower_volume=lower_volume,
            restore_volume=restore_volume,
            open_app_window=open_app_window,
            worker_creationflags=CREATE_NO_WINDOW,
            relaunch=partial(relaunch, os_kind=OsKind.WINDOWS),
            send_paste=send_paste,
            send_enter=send_enter,
            create_hotkey_listener=_create_pynput_listener,
            qt_platform=None,
            open_key_sender=_do_nothing,
            close_key_sender=_do_nothing,
            validate_hotkeys=validate_hotkeys,
        )

    # Linux のセッションで分ける
    if display_session is DisplaySession.WAYLAND:
        # Wayland のセッション: uinput のキーの送信・GNOME のショートカット・XWayland の xclip と xcb（python-evdev を読み込むため Windows では import しない）
        from voice_paste.integrations.browser.opener_linux import open_app_window_linux
        from voice_paste.integrations.keyboard.sender_wayland import UInputKeyboard
        from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener, validate_gnome_hotkeys
        from voice_paste.runtime.single_instance_linux import acquire_single_instance_linux

        use_xclip_clipboard()
        keyboard = UInputKeyboard()
        return PlatformAdapters(
            acquire_single_instance=partial(acquire_single_instance_linux, lock_file=lock_file),
            lower_volume=None,
            restore_volume=None,
            open_app_window=open_app_window_linux,
            worker_creationflags=0,
            relaunch=partial(relaunch, os_kind=OsKind.LINUX),
            send_paste=keyboard.send_paste,
            send_enter=keyboard.send_enter,
            create_hotkey_listener=GnomeShortcutListener,
            qt_platform=QT_PLATFORM_XCB,
            open_key_sender=keyboard.open,
            close_key_sender=keyboard.close,
            validate_hotkeys=validate_gnome_hotkeys,
        )

    # Xorg のセッション: 何もしない音量・Chromium 系のブラウザ・flock の排他・端末アプリを見分ける貼り付け（fcntl・python-xlib を読み込むため Windows では import しない）
    from voice_paste.integrations.browser.opener_linux import open_app_window_linux
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux
    from voice_paste.runtime.single_instance_linux import acquire_single_instance_linux

    return PlatformAdapters(
        acquire_single_instance=partial(acquire_single_instance_linux, lock_file=lock_file),
        lower_volume=None,
        restore_volume=None,
        open_app_window=open_app_window_linux,
        worker_creationflags=0,
        relaunch=partial(relaunch, os_kind=OsKind.LINUX),
        send_paste=send_paste_linux,
        send_enter=send_enter,
        create_hotkey_listener=_create_pynput_listener,
        qt_platform=None,
        open_key_sender=_do_nothing,
        close_key_sender=_do_nothing,
        validate_hotkeys=validate_hotkeys,
    )


def _create_pynput_listener(
    _name: str, _lock: SingleInstanceLock | LinuxSingleInstanceLock
) -> HotkeyListener:
    """pynput のホットキーの受付を作る（排他の名前と排他は使わない）。Windows と Linux の Xorg のセッションの create_hotkey_listener。"""
    return HotkeyListener()


def parse_args(argv: list[str]) -> CliArgs:
    """argparse で `--data-dir` を読む。"""
    parser = argparse.ArgumentParser(prog="voice_paste")
    # 置き場所が無ければ既定の置き場所を使う（非機能要件テストは一時フォルダを渡して普段使いに触れない）
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
    """常駐中の定期の削除。今の設定と、処理中の録音セッションの ID（一時の音声を残す）を引いて purge_old_files を呼ぶ。"""

    def _active_session_ids() -> set[str]:
        """処理中の録音セッションの ID を返す（待機中は空）。"""
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
    """設定の保持期間を過ぎたログと履歴を削除する。"""
    # 1. 保持期間を過ぎた日付のログを削除する
    purge_old_logs(paths.log_dir, settings.logging.retention_days, local_today())

    # 2. 履歴を残す設定か
    if settings.history.enabled:
        # 残す: 保持期間を過ぎた履歴のフォルダと、取り残された一時の音声を削除する
        purge_expired(
            retention_days=settings.history.retention_days,
            paths=paths,
            now=_local_now,
            active_session_ids=active_session_ids,
        )
    # 残さない: 履歴は削除しない


def _jitter(upper: float) -> float:
    """0 以上 upper 以下の乱数を返す（再送の間隔のフルジッター）。"""
    return random.uniform(0, upper)  # noqa: S311 暗号用途ではない


def _correct(
    text: str, glossary_preset: str | None, *, settings: Settings, settings_dir: Path
) -> str:
    """文字起こしのたびに、補正に使う用語集のプリセットを引き、その用語集を全て読み直して補正する。"""
    # 文頭・文末の文言を削除してから、用語集で置き換える（用語集の置き換えで文言の形式が変わる前に当てる）
    stripped = strip_edge_phrases(text, settings.edge_phrases)
    preset = pick_glossary_preset(settings, settings_dir, requested=glossary_preset)
    glossaries = list_preset_glossaries(preset, resolve_glossaries(settings, settings_dir))
    # プリセットに並べた用語集の順に読み、1 本の並びにつなぐ（読めない CSV は load_glossary が空を返すので飛ばされる）
    loaded = [(glossary.name, load_glossary(glossary.path)) for glossary in glossaries]
    entries = [entry for _name, rows in loaded for entry in rows]
    counts = "・".join(f"{name} {len(rows)} 行" for name, rows in loaded)
    logger.info(f"用語集で補正する（{preset.name}・補正に使う {counts or '用語集なし'}）")
    return apply_glossary(stripped, entries)


def _current_hint(store: SettingsStore) -> str | None:
    """今の設定の有効なヒントの語を読点でつないだ手がかりを返す。有効な語が無ければ None を返す。"""
    return join_hint_words(store.get().hint_presets) or None


def _deliver_session(
    session: Session,
    outcome: TranscriptionOutcome,
    *,
    enabled_ids: frozenset[str],
    outputs: tuple[OutputSpec, ...],
    preset_kinds: tuple[PresetKindSpec, ...],
) -> None:
    """Session を入口・選んだ出力先・選んだプリセット・コールバック先に分けて、出力先の deliver へ渡す（出力先は録音セッションを import しない）。"""
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


def _make_paste(
    get_settings: Callable[[], Settings], send_paste: Callable[[str], None]
) -> Callable[[], None]:
    """呼ぶたびに設定の貼り付けのキーで、OS ごとの貼り付けのキーの送信を呼ぶ関数を作る。"""

    def paste() -> None:
        """設定の貼り付けのキーで貼り付けのキーを送信する。"""
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


def _wire_preset_kinds(
    get_settings: Callable[[], Settings],
    *,
    open_window: Callable[[str], None],
    send_paste: Callable[[str], None],
    send_enter_fn: SendEnterFn | None = None,
) -> tuple[PresetKindSpec, ...]:
    """プリセットの種類の一覧の各 handler に、種類ごとの外部連携の関数と設定の値を部分適用して返す。

    send_enter_fn はブラウザ添付が Enter を送信する関数（PlatformAdapters.send_enter）。渡さなければ sender.py の send_enter を使う。
    """
    # 1. 届けるたびに設定を読む関数を作る
    paste = _make_paste(get_settings, send_paste)

    def get_enter_delay_sec() -> float:
        """設定の貼り付けて送信の、貼り付けてから Enter を送信するまでの秒数を返す。"""
        return read_enter_delay_sec(get_settings())

    def get_open_delay_sec() -> float:
        """設定のブラウザ添付の、画面を開いてから貼り付けるまでの秒数を返す。"""
        return get_settings().preset_options.browser.open_delay_sec

    def get_timeout_sec() -> float:
        """エンドポイントへ送信するときのタイムアウトの秒数を返す。"""
        return get_settings().preset_options.endpoint.timeout_sec

    # 2. 種類ごとに、handler へ注入するものを決める
    injections: dict[str, dict[str, object]] = {
        "browser": {
            "copy": copy_to_clipboard,
            "open_window": open_window,
            "paste": paste,
            "send_enter": send_enter if send_enter_fn is None else send_enter_fn,
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


def _ignore_engine_stop(_stop: Callable[[], None]) -> None:
    """エンジンを止める関数を受け取っても控えない（build_handlers の on_engine_created の既定）。"""


def build_handlers(
    settings: Settings,
    paths: AppPaths,
    notify: NotifyFn,
    report_progress: ProgressFn,
    notify_copied: Callable[[str], None],
    *,
    adapters: PlatformAdapters,
    environ: Mapping[str, str],
    unavailable: frozenset[Feature],
    on_engine_created: Callable[[Callable[[], None]], None] = _ignore_engine_stop,
) -> Handlers:
    """設定からエンジン・録音機・出力先・履歴を組み立て、SessionDeps を作って SessionManager と SessionApiDeps を返す。

    on_engine_created は、エンジンの準備（ワーカーの ready の待ち）を始める前に、エンジンを止める関数を受け取る。
    """
    # 1. 設定を SettingsStore に入れる。以降の配線は設定を値でなく SettingsStore.get から読む
    store = SettingsStore(settings)

    # 2. 設定のエンジンで、文字起こしの関数と、エンジンを止める関数を作る
    engine, stop_engine, active_engine = _build_engine(
        settings,
        paths,
        adapters,
        environ,
        on_engine_created,
        get_vocabulary=lambda: collect_hint_vocabulary(store.get().hint_presets),
        get_haas_settings=lambda: store.get().transcription.haas,
        notify=notify,
        unavailable=unavailable,
    )

    # 3. 連続録音の話し声の判定に使う VAD のセッションを 1 回だけ読む（読めなければ立ち上げたエンジンを止めて起動の失敗にする）
    try:
        vad_session = load_vad_session()
    except StartupError:
        stop_engine()
        raise

    # 4. 録音機に音量とマイクの入力の関数と、SettingsStore から録音の設定を返す関数と、VAD のセッションを部分適用した話し声の判定を作る関数を渡す
    # 音量を下げる機能を使えない OS か
    if Feature.LOWER_VOLUME in unavailable:
        # 使えない: 音量を変えない関数を渡す
        lower_volume, restore_volume = lower_volume_noop, restore_volume_noop
    else:
        lower_volume, restore_volume = adapters.lower_volume, adapters.restore_volume
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
        paste=_make_paste(store.get, adapters.send_paste),
        send_enter=adapters.send_enter,
        sleep=time.sleep,
        jitter=_jitter,
        post=post_json,
        get_settings=store.get,
        notify_copied=notify_copied,
    )
    wired_outputs = _wire_outputs(output_deps, OUTPUTS)
    wired_preset_kinds = _wire_preset_kinds(
        store.get,
        open_window=adapters.open_app_window,
        send_paste=adapters.send_paste,
        send_enter_fn=adapters.send_enter,
    )

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
    def correct(text: str, glossary_preset: str | None) -> str:
        """今の設定で、指定した用語集のプリセット（None は設定で選んでいるプリセット）の用語集で補正する。"""
        return _correct(
            text,
            glossary_preset,
            settings=store.get(),
            settings_dir=paths.settings_file.parent,
        )

    def glossary_preset_exists(name: str) -> bool:
        """今の設定の用語集のプリセットの一覧に、その名前があるか。"""
        presets = resolve_glossary_presets(store.get(), paths.settings_file.parent)
        return any(preset.name == name for preset in presets)

    # 7. SessionDeps を組み、API の録音セッションの上限時間と連続録音の上限時間（起動時の設定。再起動で効く）と共に SessionManager を作る
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
        transcribe=partial(
            transcribe, engine=engine, get_hint=partial(_current_hint, store)
        ),
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

    # 8. SessionManager と、設定の許可ホストを部分適用したコールバック先の確かめと、用語集のプリセットの確かめを SessionApiDeps に束ねる
    session_api = SessionApiDeps(
        session_manager=session_manager,
        is_callback_allowed=partial(
            is_callback_allowed, allowed_hosts=frozenset(settings.api.allowed_callback_hosts)
        ),
        glossary_preset_exists=glossary_preset_exists,
    )

    # 9. 外の端末のブラウザの機能を使えない OS では配線せず、使える OS ではブラウザの文字起こしを配線する
    web_api = (
        None
        if Feature.WEB_TRANSCRIPTION in unavailable
        else _wire_web_api(
            store,
            paths,
            engine=engine,
            correct=correct,
            glossary_preset_exists=glossary_preset_exists,
            active_engine=active_engine,
        )
    )

    # 10. start_local_session に SessionManager と notify を部分適用する
    return Handlers(
        session_manager=session_manager,
        session_api=session_api,
        web_api=web_api,
        settings_store=store,
        start_local_session=partial(
            start_local_session, session_manager=session_manager, notify=notify
        ),
        recorder_level=recorder.level,
        stop_engine=stop_engine,
        active_engine=active_engine,
    )


def _wire_web_api(
    store: SettingsStore,
    paths: AppPaths,
    *,
    engine: EngineFn,
    correct: Callable[[str, str | None], str],
    glossary_preset_exists: Callable[[str], bool],
    active_engine: EngineName,
) -> WebApiDeps:
    """ブラウザの文字起こしを配線する（履歴を残すかと用語集のプリセットの一覧はそのたびに SettingsStore から引く。ワーカースレッドはまだ立てない）。"""

    def list_glossary_preset_choices() -> GlossaryPresetChoices:
        """今の設定の用語集のプリセットの名前の一覧と、設定で選んでいるプリセットの名前を返す。"""
        settings_dir = paths.settings_file.parent
        presets = resolve_glossary_presets(store.get(), settings_dir)
        active = pick_glossary_preset(store.get(), settings_dir)
        return GlossaryPresetChoices(presets=[preset.name for preset in presets], active=active.name)

    def store_web_audio_now(job_id: str, source: Path) -> Path:
        """今の設定で履歴を残すかを引いて、ブラウザの音声を保存する。"""
        return store_web_audio(
            job_id,
            source,
            history_enabled=store.get().history.enabled,
            paths=paths,
            now=_local_now,
        )

    web_queue = WebJobQueue(
        WebTranscriptionDeps(
            store_audio=store_web_audio_now,
            transcribe=partial(
                transcribe, engine=engine, get_hint=partial(_current_hint, store)
            ),
            correct=correct,
            append_text=partial(append_text, paths=paths),
            discard_temporary=partial(discard_temporary, paths=paths),
        )
    )
    return WebApiDeps(
        queue=web_queue,
        probe_audio=probe_audio,
        tmp_dir=paths.tmp_dir / WEB_TMP_DIR_NAME,
        glossary_preset_exists=glossary_preset_exists,
        list_glossary_presets=list_glossary_preset_choices,
        reports_progress=_reports_progress(active_engine),
    )


HAAS_FALLBACK_MESSAGE: str = "Haas のサーバーへ接続できないため、ローカルの Whisper で起こします。"
"""Haas からローカルの Whisper へ切り戻したときの知らせの文。"""

HAAS_SETTING_LABELS: dict[str, str] = {"model": "モデル", "dtype": "計算の精度", "device": "装置"}
"""動いている Haas のサーバーが設定と違うときの通知に出す項目の名前（画面設計『トレイの通知』の {違う項目}）。"""

HAAS_SETTING_SEPARATOR: str = "・"
"""通知に出す違う項目の名前をつなぐ文字。"""


def _build_engine(
    settings: Settings,
    paths: AppPaths,
    adapters: PlatformAdapters,
    environ: Mapping[str, str],
    on_engine_created: Callable[[Callable[[], None]], None],
    *,
    get_vocabulary: Callable[[], list[HintVocabularyWord]],
    get_haas_settings: Callable[[], HaasSettings],
    notify: NotifyFn,
    unavailable: frozenset[Feature],
) -> tuple[EngineFn, Callable[[], None], EngineName]:
    """設定のエンジンで、文字起こしの関数と、エンジンを止める関数と、動いているエンジンを作る。止める関数は準備を始める前に on_engine_created へ渡す。準備できなければ StartupError。"""
    # 設定のエンジンは何か
    if EngineName(settings.transcription.engine) is EngineName.OPENAI:
        # OpenAI API: API キーを読み、OpenAI API の文字起こしを作る（文字起こしワーカーは起動せず、止めるものも無い）
        transcriber = OpenAITranscriber(
            settings=settings.transcription.openai,
            api_key=read_openai_api_key(paths.openai_api_key_file, environ),
        )
        logger.info(f"文字起こしのエンジンは OpenAI API（{settings.transcription.openai.model}）")
        on_engine_created(_stop_nothing)
        return transcriber.transcribe, _stop_nothing, EngineName.OPENAI

    # Haas: サーバーを確かめる。使えなければローカルの Whisper へ切り戻す
    if EngineName(settings.transcription.engine) is EngineName.HAAS:
        haas_settings = settings.transcription.haas
        server = HaasServer(settings=haas_settings)
        on_engine_created(server.stop)
        try:
            if Feature.HAAS_ENGINE in unavailable:
                raise EngineError("この OS では使えない")
            differs = server.ensure_started()
        except EngineError as error:
            logger.warning(f"Haas のサーバーへ接続できないためローカルの Whisper で起こす（{error}）")
            notify("engine_fallback", HAAS_FALLBACK_MESSAGE)
        else:
            # 起動の前から動いていたサーバーが設定と違えば知らせ、そのサーバーのまま起こす
            if differs:
                names = HAAS_SETTING_SEPARATOR.join(HAAS_SETTING_LABELS[item] for item in differs)
                notify("engine_settings_mismatch", names)
            transcriber = HaasTranscriber(
                port=haas_settings.port,
                get_vocabulary=get_vocabulary,
                get_settings=get_haas_settings,
            )
            return transcriber.transcribe, server.stop, EngineName.HAAS

    # ローカルの Whisper
    engine, stop = _start_local_whisper(settings, paths, adapters, on_engine_created)
    return engine, stop, EngineName.LOCAL_WHISPER


def _start_local_whisper(
    settings: Settings,
    paths: AppPaths,
    adapters: PlatformAdapters,
    on_engine_created: Callable[[Callable[[], None]], None],
) -> tuple[EngineFn, Callable[[], None]]:
    """依存が入っているかを確かめ、文字起こしワーカーを作って起動する。準備できなければ StartupError。"""
    ensure_local_whisper_installed()
    worker = WhisperWorkerClient(
        settings=settings.transcription.local_whisper,
        ready_timeout_sec=WORKER_READY_TIMEOUT_SEC,
        log_dir=paths.log_dir,
        stop_timeout_sec=WORKER_STOP_TIMEOUT_SEC,
        creationflags=adapters.worker_creationflags,
    )
    # ready を待つ間に止められるよう、起動する前に止める関数を渡す
    on_engine_created(worker.stop)
    try:
        worker.start()
    except EngineError as error:
        raise StartupError(f"文字起こしのエンジンを準備できませんでした: {error}") from error
    return worker.transcribe, worker.stop


def _stop_nothing() -> None:
    """止めるものが無いエンジン（OpenAI API）の停止の代わりに、何もしない。"""


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

    def is_local_transcribing() -> bool:
        """ホットキー・トレイの録音が文字起こし中か。"""
        session = session_manager.current()
        return (
            session is not None
            and session.entry != Entry.API
            and session.state == SessionState.TRANSCRIBING
        )

    def on_start() -> None:
        """ホットキー・トレイの録音中なら出力先で確定し（出力先が無ければ隠した録音の画面を戻す指示を出す）、文字起こし中なら同じホットキーの出力先へ差し替え、そうでなければ録音を始める。"""
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
        # 自分の録音の文字起こし中: 同じホットキーの出力先があれば、録音を始めずにその出力先へ差し替える
        if confirm_output_id is not None and is_local_transcribing():
            session_manager.switch_output(confirm_output_id)
            return
        start_local_session(Entry.HOTKEY)

    def on_output(output_id: str) -> None:
        """ホットキー・トレイの録音が文字起こし中ならその出力先へ差し替え、そうでなければその出力先で確定する（差し替えられない録音セッションは SessionManager が断る）。"""
        if is_local_transcribing():
            session_manager.switch_output(output_id)
        else:
            session_manager.complete(output_id=output_id)

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
        # オンの出力先のホットキー（録音開始と同じキーを除く）: その出力先で確定する（文字起こし中はその出力先へ差し替える）
        if output.enabled and output.hotkey.lower() != start_hotkey.lower():
            bindings[output.hotkey] = partial(on_output, output.id)
    for preset in settings.presets:
        # 有効なプリセットのホットキー: そのプリセットで確定する
        if preset.enabled:
            bindings[preset.hotkey] = partial(session_manager.complete, preset=preset)
    # 空のホットキーは登録しない（重なりは Settings の確かめが断っている）
    return {hotkey: handler for hotkey, handler in bindings.items() if hotkey}


def apply_settings(
    settings: Settings,
    glossary_rows: Mapping[Path, Sequence[GlossaryEntry]],
    *,
    paths: AppPaths,
    store: SettingsStore,
    check_hotkeys: Callable[[Iterable[str]], None],
    save_glossary: Callable[[Path, Sequence[GlossaryEntry]], None],
) -> bool:
    """設定画面で確かめた設定と行を変えた用語集の CSV を書き、反映が immediate の項目を動いている常駐アプリに効かせる。

    新しい設定のホットキーを pynput が読めなければ、何も書かず入れ替えずに HotkeyError を送出する。
    用語集の CSV か settings.yaml を書けなければ OSError のまま伝え、SettingsStore は入れ替えない。
    """
    # 1. 新しい設定で受け付けるホットキーを確かめる
    check_hotkeys(_collect_hotkeys(settings))

    # 2. glossary_rows の用語集の CSV を書く（書けなければ OSError のまま伝える。先に書けた CSV は戻さない）
    for glossary_path, rows in glossary_rows.items():
        save_glossary(glossary_path, rows)

    # 3. settings.yaml へ、今効いている設定から変わったキーだけを書く（書けなければ OSError のまま伝え、SettingsStore は入れ替えない）
    restart_needed = save_settings(paths, store.get(), settings)

    # 4. SettingsStore を入れ替える（ホットキーは設定画面が閉じたときに今の設定で張り直す）
    store.replace(settings)
    logger.info(
        f"設定を保存した（{paths.settings_file}・再起動が要る: {restart_needed}・"
        f"書いた用語集の CSV: {len(glossary_rows)} 件）"
    )
    return restart_needed


def reset_applied_settings(
    *, paths: AppPaths, store: SettingsStore, model: type[Settings]
) -> tuple[Settings, bool]:
    """環境の値から全てのキーを外し、読み直した設定に SettingsStore を入れ替える。読み直した設定と再起動が要る項目が変わったかを返す。"""
    # 1. 環境の値のキーを全て外す
    reset_settings(paths.settings_file)

    # 2. 設定を読み直す（読めなければ SettingsStore を入れ替えずに SettingsError のまま伝える）
    settings = load_settings(paths, model)

    # 3. 再起動が要るかを控えてから入れ替える
    restart_needed = has_restart_change(store.get(), settings)
    store.replace(settings)
    logger.info(f"設定を既定に戻した（{paths.settings_file}・再起動が要る: {restart_needed}）")
    return settings, restart_needed


def _output_titles() -> dict[str, str]:
    """画面に出す出力先の名前（出力先の ID → 名前。API 専用の出力先を除く）を返す。"""
    return {spec.id: spec.title for spec in OUTPUTS if not spec.api_only}


def build_ui_deps(
    handlers: Handlers,
    paths: AppPaths,
    save_settings: Callable[[Settings, Mapping[Path, Sequence[GlossaryEntry]]], bool],
    reset_settings: Callable[[], tuple[Settings, bool]],
    request_restart: Callable[[], None],
    request_quit: Callable[[], None],
    hotkey_listener: HotkeyListener | GnomeShortcutListener,
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
        switch_output=session_manager.switch_output,
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
        list_glossaries=lambda: resolve_glossaries(store.get(), paths.settings_file.parent),
        list_glossary_presets=lambda: resolve_glossary_presets(
            store.get(), paths.settings_file.parent
        ),
        read_glossary=read_glossary_rows,
        new_glossary_path=partial(
            next_glossary_path, directory=paths.settings_file.parent / GLOSSARIES_DIR_NAME
        ),
        copy=copy_to_clipboard,
        reset_settings=reset_settings,
        default_settings=partial(load_default_settings, paths.defaults_file, SETTINGS_MODEL),
        hidden_setting_keys=hidden_setting_keys(unavailable_features(CURRENT_OS)),
        reports_progress=_reports_progress(handlers.active_engine),
    )


def _reports_progress(engine: EngineName) -> bool:
    """動いているエンジンが、区間ごとの進みを知らせるか（ローカルの Whisper は知らせ、OpenAI API と Haas は知らせない）。"""
    return engine is EngineName.LOCAL_WHISPER


def _apply_current_theme(
    app: QApplication, get_settings: Callable[[], Settings], *, image_dir: Path
) -> None:
    """今の設定の ui.theme で画面の明暗を当て直す。"""
    apply_theme(app, get_settings().ui.theme, image_dir=image_dir)


def _watch_system_theme(app: QApplication, reapply: Callable[[], None]) -> None:
    """OS の明暗が変わったときに、画面の明暗を当て直す（ui.theme が system のときに配色が替わる）。"""
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: reapply())


def _build_idle_ui_deps(
    settings: Settings,
    paths: AppPaths,
    app: QApplication,
    request_restart: Callable[[], None],
    request_quit: Callable[[], None],
    check_hotkeys: Callable[[Iterable[str]], None],
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
        switch_output=do_nothing,
        level=lambda: 0.0,
        get_settings=store.get,
        save_settings=partial(
            apply_settings,
            paths=paths,
            store=store,
            check_hotkeys=check_hotkeys,
            save_glossary=save_glossary,
        ),
        settings_dir=paths.settings_file.parent,
        log_dir=paths.log_dir,
        request_restart=request_restart,
        request_quit=request_quit,
        suspend_hotkeys=do_nothing,
        resume_hotkeys=do_nothing,
        output_titles=_output_titles(),
        apply_theme=partial(_apply_current_theme, app, store.get, image_dir=paths.ui_image_dir),
        list_glossaries=lambda: resolve_glossaries(store.get(), paths.settings_file.parent),
        list_glossary_presets=lambda: resolve_glossary_presets(
            store.get(), paths.settings_file.parent
        ),
        read_glossary=read_glossary_rows,
        new_glossary_path=partial(
            next_glossary_path, directory=paths.settings_file.parent / GLOSSARIES_DIR_NAME
        ),
        copy=copy_to_clipboard,
        reset_settings=partial(
            reset_applied_settings, paths=paths, store=store, model=SETTINGS_MODEL
        ),
        default_settings=partial(load_default_settings, paths.defaults_file, SETTINGS_MODEL),
        hidden_setting_keys=hidden_setting_keys(unavailable_features(CURRENT_OS)),
        reports_progress=_reports_progress(EngineName(settings.transcription.engine)),
    )


class _StartupBuild(QObject):
    """配線をメインスレッドの外のスレッドで流し、結果を done でメインスレッドへ戻す。配線の間に抜けたときはエンジンを止める。"""

    done = Signal(object)
    """配線の結果（Handlers か StartupError）。cancel の後は送出しない。"""

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        # build_handlers の on_engine_created で控えた、エンジンを止める関数
        self._stop_engine: Callable[[], None] | None = None
        self._cancelled = False
        # _stop_engine・_cancelled の読み書きと done の送出を 1 つずつにする
        self._lock = threading.Lock()

    def start(self, build: Callable[[Callable[[Callable[[], None]], None]], Handlers]) -> None:
        """渡した配線をデーモンスレッドで流し、結果を done で渡す。"""
        self._thread = threading.Thread(
            target=self._run, args=(build,), name=STARTUP_THREAD_NAME, daemon=True
        )
        self._thread.start()

    def _run(self, build: Callable[[Callable[[Callable[[], None]], None]], Handlers]) -> None:
        """配線を呼び、取り消されていなければ結果を done で送出する。"""
        # 1. 配線を呼ぶ（エンジンを準備できなければ、その StartupError を結果にする）
        result: Handlers | StartupError
        try:
            result = build(self._register_stop)
        except StartupError as error:
            result = error
        except Exception as error:
            # 想定外の例外: ログに残し、StartupError にしてトレイを失敗にする（準備中のまま止めない）
            logger.exception("起動の配線で想定外のエラーが起きた")
            result = StartupError(f"起動の配線で想定外のエラーが起きた（{error!r}）")

        # 2. 取り消されていなければ結果を送出する
        with self._lock:
            if not self._cancelled:
                self.done.emit(result)
                return
        # 取り消された後に配線できた（StartupError でない）: 立ち上げたエンジンを止めて捨てる
        if not isinstance(result, StartupError):
            result.stop_engine()

    def _register_stop(self, stop: Callable[[], None]) -> None:
        """エンジンを止める関数を控える。既に取り消されていれば、すぐ止める。"""
        with self._lock:
            self._stop_engine = stop
            cancelled = self._cancelled
        if cancelled:
            stop()

    def cancel(self, timeout_sec: float) -> None:
        """控えたエンジンを止め、配線のスレッドの終わりを待つ。以降は done を送出しない。"""
        # 1. 取り消したことにして、控えた止める関数を引く
        with self._lock:
            self._cancelled = True
            stop = self._stop_engine

        # 2. ロックを放してから止める（ワーカーが終わり、配線は StartupError で終わる）
        if stop is not None:
            stop()

        # 3. スレッドの終わりを待つ（待ちきれなければ、そのまま戻る）
        if self._thread is None:
            return
        self._thread.join(timeout_sec)
        if self._thread.is_alive():
            logger.warning("起動の配線が終わらないまま終える")


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
    hotkey_listener: HotkeyListener | GnomeShortcutListener | None = None
    close_key_sender: Callable[[], None] | None = None
    """キーの送信の機器を閉じる関数（開こうとした後に入る）。"""
    controller: UiController | None = None
    """画面の振り分け。Qt の部品は参照が切れると消えるため、終わりまで持つ。"""
    startup: _StartupBuild | None = None
    """配線のスレッド。参照が切れると消えるため、終わりまで持つ。"""
    building: bool = False
    """配線を流していて、まだ結果を受けていないか。"""


def _stop_all(running: _Running, tray: Tray) -> None:
    """新しい開始が来ないように入口とタイマーを先に止め、録音を捨て、エンジンを止め、トレイを削除する。"""
    # 配線を流している間に抜けた: 控えたエンジンを止め、配線のスレッドの終わりを待つ
    if running.building and running.startup is not None:
        running.building = False
        running.startup.cancel(STARTUP_CANCEL_TIMEOUT_SEC)
    if running.hotkey_listener is not None:
        running.hotkey_listener.stop()
    for timer in running.timers:
        timer.stop()
    if running.runner is not None:
        running.runner.stop()
    if running.handlers is not None:
        running.handlers.session_manager.close()
        # ブラウザの音声のキューを始めていれば閉じる
        if running.handlers.web_api is not None:
            running.handlers.web_api.queue.close()
        running.handlers.stop_engine()
    if running.close_key_sender is not None:
        running.close_key_sender()
    tray.hide()


def _create_application() -> QApplication:
    """QApplication（最後の窓を閉じても終わらない）を作る。既にあればそれを使う。"""
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    return app


def _install_signal_handlers(app: QApplication) -> QTimer:
    """SIGINT・SIGBREAK・SIGTERM で QApplication.quit を呼ぶ（SIGTERM はログアウト・systemctl stop で届き、片付けを通す）。イベントループの中で Python へ戻る空のタイマーを返す。"""
    wake_timer = QTimer(app)
    wake_timer.timeout.connect(lambda: None)
    wake_timer.start(WAKE_INTERVAL_MS)
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    signal.signal(signal.SIGTERM, lambda *_args: app.quit())
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

    # 3. デスクトップのセッションを判定して OS に合った実装を選び、OS で使えない機能を引き、置き場所ごとの名前で単一インスタンスを確保する（前のプロセスが動いていれば、終わるよう頼んで放されるのを待つ）
    adapters = select_platform_adapters(
        CURRENT_OS,
        lock_file=paths.lock_file,
        display_session=detect_display_session(os.environ),
    )
    unavailable = unavailable_features(CURRENT_OS)
    lock_name = instance_name(paths.settings_file.parent)
    try:
        lock = adapters.acquire_single_instance(lock_name, SINGLE_INSTANCE_TIMEOUT_SEC)
    except StartupError as error:
        # トレイを出す前のため、ログにだけ残して終わる
        logger.error(f"起動に失敗した（{error}）")
        return EXIT_FAILED

    # 4〜11. 排他を持ったまま起動して回し、どう抜けても最後に排他を放す
    try:
        exit_code, restart = _run_service(paths, lock, lock_name, exec_loop, adapters, unavailable)
    finally:
        lock.release()

    # 12. 再起動を頼まれていれば、同じ引数で起動し直す（排他を放した後のため、次のプロセスは待たずに取れる）
    if restart:
        adapters.relaunch(argv_used)
    return exit_code


def _run_service(
    paths: AppPaths,
    lock: SingleInstanceLock | LinuxSingleInstanceLock,
    lock_name: str,
    exec_loop: Callable[[QApplication], int],
    adapters: PlatformAdapters,
    unavailable: frozenset[Feature],
) -> tuple[int, bool]:
    """排他を持った状態で、画面の用意・起動・イベントループ・片付けを行い、終了コードと再起動の要否を返す。"""
    # 5. Qt のプラットフォームが決まっていて、環境変数で指定されていなければ入れてから、QApplication・UiBridge・Tray を作り、スタイルを当ててトレイに準備中を出す
    if adapters.qt_platform is not None:
        os.environ.setdefault(QT_PLATFORM_ENV, adapters.qt_platform)
    app = _create_application()
    # 後から起動したプロセスに終わるよう頼まれたら、メインスレッドで QApplication.quit を呼ぶ
    lock.on_quit_requested(
        lambda: QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)
    )
    bridge = UiBridge()
    tray = Tray(paths.settings_file.parent, paths.log_dir)
    apply_theme(app, "system", image_dir=paths.ui_image_dir)
    tray.set_state(TrayState.STARTING, busy=False)
    wake_timer = _install_signal_handlers(app)
    exit_request = _ExitRequest(app)
    running = _Running()
    # 配線の間も抜けられるよう、トレイの「再起動」「終了」をつなぐ（配線の結果を受けたら外す）
    tray.restart_requested.connect(exit_request.request_restart)
    tray.quit_requested.connect(exit_request.request_quit)

    try:
        _start_services(
            app, bridge, tray, paths, exit_request, running, (adapters, lock, lock_name, unavailable)
        )
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
    platform: tuple[
        PlatformAdapters, SingleInstanceLock | LinuxSingleInstanceLock, str, frozenset[Feature]
    ],
) -> None:
    """設定を読み、配線をメインスレッドの外のスレッドで始める。配線の結果は _finish_startup がメインスレッドで受ける。

    platform は OS ごとの実装・取った排他・排他の名前・OS で使えない機能。
    """
    adapters, _lock, _lock_name, unavailable = platform
    ui_notify = partial(notify, bridge=bridge)
    ui_report_progress = partial(report_progress, bridge=bridge)
    ui_notify_copied = partial(notify_copied, bridge=bridge)

    # 5. 設定を読む（読めなければトレイを失敗にして知らせ、設定を修正して再起動できるようにする）
    try:
        settings = load_settings(paths, SETTINGS_MODEL)
    except SettingsError as error:
        logger.error(f"起動に失敗した（{error}）")
        tray.set_failed(settings_enabled=False)
        tray.show_failure("settings_invalid", str(error), paths=error.paths)
        return

    # 6. 設定の ui.theme で画面の明暗を当て直し、ルートロガーのレベルを設定のログのレベルにし、保持期間で古いログと履歴を削除する（処理中の録音セッションは無いため、一時の音声も全て削除する対象にする）
    apply_theme(app, settings.ui.theme, image_dir=paths.ui_image_dir)
    logging.getLogger().setLevel(settings.logging.level)
    purge_old_files(settings, paths=paths, active_session_ids=set)
    enabled_outputs = [output.id for output in settings.outputs if output.enabled]
    logger.info(
        f"設定を読んだ（{paths.settings_file}、エンジン: {settings.transcription.engine}、"
        f"オンの出力先: {', '.join(enabled_outputs)}）"
    )

    # 7. 配線をメインスレッドの外のスレッドに流す（流している間もイベントループを回し、トレイを準備中のまま出す）。結果はメインスレッドで受ける
    build = partial(
        build_handlers,
        settings,
        paths,
        ui_notify,
        ui_report_progress,
        ui_notify_copied,
        adapters=adapters,
        environ=os.environ,
        unavailable=unavailable,
    )
    # 配線の間の知らせ（Haas からの切り戻し）はトレイが受ける（画面の振り分けは配線の後に作る）
    bridge.notified.connect(tray.show_failure, Qt.ConnectionType.QueuedConnection)
    startup = _StartupBuild()
    running.startup = startup
    running.building = True
    startup.done.connect(
        lambda result: _finish_startup(
            result, app, bridge, tray, paths, exit_request, running, platform, settings
        ),
        Qt.ConnectionType.QueuedConnection,
    )
    startup.start(lambda register_stop: build(on_engine_created=register_stop))


def _finish_startup(
    result: Handlers | StartupError,
    app: QApplication,
    bridge: UiBridge,
    tray: Tray,
    paths: AppPaths,
    exit_request: _ExitRequest,
    running: _Running,
    platform: tuple[
        PlatformAdapters, SingleInstanceLock | LinuxSingleInstanceLock, str, frozenset[Feature]
    ],
    settings: Settings,
) -> None:
    """配線の結果をメインスレッドで受け、画面・API・ホットキー・上限のタイマーを立てる。立てたものは running に入れる。"""
    # 抜けた後に届いた結果は受けない（片付けで取り消し済み）
    if not running.building:
        return
    running.building = False
    adapters, lock, lock_name, _unavailable = platform
    ui_notify = partial(notify, bridge=bridge)
    show_recording_window = partial(notify, "show_recording_window", bridge=bridge)

    # 7. 配線の間だけつないでいた「再起動」「終了」と知らせを外す（以降は画面の振り分けが受ける）
    bridge.notified.disconnect(tray.show_failure)
    tray.restart_requested.disconnect(exit_request.request_restart)
    tray.quit_requested.disconnect(exit_request.request_quit)

    # エンジンを準備できなければトレイを失敗にして知らせ、設定画面だけを使えるようにする
    if isinstance(result, StartupError):
        error = result
        logger.error(f"起動に失敗した（{error}）")
        tray.set_failed(settings_enabled=True)
        deps = _build_idle_ui_deps(
            settings,
            paths,
            app,
            exit_request.request_restart,
            exit_request.request_quit,
            adapters.validate_hotkeys,
        )
        _watch_system_theme(app, deps.apply_theme)
        running.controller = _build_controller(bridge, tray, deps)
        tray.show_failure("engine_unavailable", str(error))
        return
    handlers = result
    running.handlers = handlers

    # 画面を作って知らせの受け手につなぐ（API の待ち受けを始められない知らせを取りこぼさないよう、API より先に）
    hotkey_listener = adapters.create_hotkey_listener(lock_name, lock)
    running.hotkey_listener = hotkey_listener
    save_settings_fn = partial(
        apply_settings,
        paths=paths,
        store=handlers.settings_store,
        check_hotkeys=adapters.validate_hotkeys,
        save_glossary=save_glossary,
    )
    deps = build_ui_deps(
        handlers,
        paths,
        save_settings_fn,
        partial(
            reset_applied_settings,
            paths=paths,
            store=handlers.settings_store,
            model=SETTINGS_MODEL,
        ),
        exit_request.request_restart,
        exit_request.request_quit,
        hotkey_listener,
        show_recording_window,
        partial(
            _apply_current_theme,
            app,
            handlers.settings_store.get,
            image_dir=paths.ui_image_dir,
        ),
    )
    _watch_system_theme(app, deps.apply_theme)
    running.controller = _build_controller(bridge, tray, deps)

    # 8. ブラウザの機能を組み込んでいれば音声のキューを始め、トークンを作り、API サーバーを起動する
    if handlers.web_api is not None:
        handlers.web_api.queue.start(handlers.web_api.tmp_dir)
    token = create_token()
    port = settings.api.port
    fastapi_app = build_fastapi(
        handlers.session_api,
        token,
        port,
        web_api=handlers.web_api,
        allowed_web_origins=settings.api.allowed_web_origins,
    )
    runner = ApiServerRunner(fastapi_app, port)
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
    # キーの送信の機器を開く（開けなければ貼り付けを使えないことを知らせて続ける。「コピーのみ」は使える）
    running.close_key_sender = adapters.close_key_sender
    try:
        adapters.open_key_sender()
    except DeliveryError as error:
        logger.error(f"キーの送信の機器を開けなかった（{error}）")
        tray.show_failure("paste_unavailable", str(error))
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
    bridge.copied.connect(controller.on_copied, Qt.ConnectionType.QueuedConnection)
    tray.set_start_hotkey(deps.get_settings().hotkeys.start)
    return controller
