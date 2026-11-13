"""main.py（parse_args・main・_StartupBuild・select_platform_adapters・start_local_session・build_hotkey_bindings・apply_settings・switch_glossary_preset・reset_applied_settings・_wire_outputs・_wire_preset_kinds）の単体テスト。

main の配線（build_handlers）・API サーバー（ApiServerRunner）・上限の打ち切りのタイマー（RepeatingTimer）・
ホットキーの受付（PlatformAdapters.create_hotkey_listener）・トレイ（Tray）・再起動（PlatformAdapters.relaunch）は偽物に差し替え、
イベントループ（exec_loop）は、配線の結果を受けて起動を終えるまでイベントを処理してから戻る関数にする（配線はメインスレッドの外で流れ、結果はイベントで届く）。
画面は offscreen の QApplication（conftest の qapp）を使い回す（main は QApplication が既にあればそれを使う）。
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn
from unittest.mock import MagicMock, call

import pytest
from PySide6.QtCore import QTimer

from tests.unit.log_helpers import read_log_records
from tests.unit.voice_paste.settings_helpers import DEFAULTS_FILE
from tests.unit.voice_paste.ui.helpers import make_session
from voice_paste.shared.errors import StartupError

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from tests.unit.voice_paste.runtime.helpers import BackgroundAcquire
    from voice_paste.features.outputs import OutputSpec, PresetKindSpec
    from voice_paste.features.outputs.types import OutputDeps
    from voice_paste.shared.constants import AppPaths
    from voice_paste.main import Handlers
    from voice_paste.shared.os_kind import DisplaySession, Feature, OsKind
    from voice_paste.shared.settings import Settings
    from voice_paste.shared.types import TranscriptionOutcome
    from voice_paste.ui.controller import UiDeps

ACQUIRE_WAIT_SEC = 5.0
"""別のスレッドで排他を取れるかが決まるのを待つ上限。"""

SHORT_ACQUIRE_TIMEOUT_SEC = 0.5
"""放されているはずの排他を取るときの待つ上限。"""

QUIT_LOOP_TIMEOUT_MS = 5000
"""終了を頼まれてもイベントループが抜けないときに、諦めて抜ける上限（ミリ秒）。"""

STARTUP_WAIT_SEC = 5.0
"""配線の結果を受けて起動を終えるまでイベントを処理する上限。"""

BUILD_WAIT_SEC = 3.0
"""配線の偽物が、止める関数・合図を待つ上限（実装が待ちを解かなくてもテストが止まらないようにする）。"""

SETTLE_SEC = 0.2
"""起きてはいけないことが起きないのを確かめるために、イベントを処理し続ける時間。"""

POLL_INTERVAL_SEC = 0.01
"""イベントを処理しながら待つときの、1 回ごとの間。"""

SIGNAL_NAMES = ("SIGINT", "SIGBREAK", "SIGTERM")
DEFAULT_HOTKEYS = {
    "<ctrl>+<alt>+d",
    "<ctrl>+<alt>+z",
    "<ctrl>+<alt>+q",
    "<ctrl>+<alt>+v",
    "<ctrl>+<alt>+c",
}
"""既定の設定で受け付けるホットキー（録音の開始と貼り付けて送信は同じキー）。"""


@pytest.fixture(autouse=True)
def restore_signal_handlers() -> Iterator[None]:
    """main が入れ替える SIGINT・SIGBREAK のハンドラを、テストの後に元へ戻す。"""
    saved = {
        name: signal.getsignal(getattr(signal, name))
        for name in SIGNAL_NAMES
        if hasattr(signal, name)
    }

    yield

    for name, handler in saved.items():
        if handler is not None:
            signal.signal(getattr(signal, name), handler)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """--data-dir に渡す空の一時フォルダを返す。"""
    path = tmp_path / "data"
    path.mkdir()
    return path


@dataclass
class Wiring:
    """main の配線を差し替えた偽物と、止める操作が呼ばれた順の記録。"""

    calls: list[str]
    build_handlers: MagicMock
    runner_class: MagicMock
    timer_class: MagicMock
    hotkey_class: MagicMock
    create_hotkey_listener: MagicMock
    tray_class: MagicMock
    relaunch: MagicMock
    build_fastapi: MagicMock
    web_api: MagicMock
    ui_deps: list[UiDeps]
    """main が build_ui_deps で作った UiDeps（作られた順）。"""
    adapter_overrides: dict[str, Any]
    """select_platform_adapters が返す PlatformAdapters の項目のうち、差し替えるもの（項目の名前 → 偽物）。main が選ぶ前に入れる。"""
    build_threads: list[str]
    """build_handlers が呼ばれたスレッドの名前（呼ばれた順）。"""

    @property
    def hotkey(self) -> MagicMock:
        """main が作ったホットキーの受付の偽物（create_hotkey_listener が返したもの）。"""
        return self.hotkey_class.return_value

    @property
    def tray(self) -> MagicMock:
        """main が作った Tray の偽物。"""
        return self.tray_class.return_value

    @property
    def runner(self) -> MagicMock:
        """main が作った ApiServerRunner の偽物。"""
        return self.runner_class.return_value

    @property
    def startup_finished(self) -> bool:
        """起動を終えたか（トレイが待機中になったか、失敗になった）。"""
        from voice_paste.ui.tray import TrayState

        return self.tray.set_failed.called or (
            call(TrayState.IDLE, busy=False) in self.tray.set_state.call_args_list
        )

    def exit_after_startup(self, app: QApplication) -> int:
        """起動を終えるまでイベントを処理して、0 を返す。main の exec_loop に渡す。"""
        wait_for_startup(app, self)
        return 0


def install_wiring(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    *,
    api_started: bool = True,
    build_error: Exception | None = None,
    build_hook: Callable[[Callable[[Callable[[], None]], None]], None] | None = None,
) -> Wiring:
    """main が使う build_handlers・ApiServerRunner・RepeatingTimer・ホットキーの受付（PlatformAdapters.create_hotkey_listener）・Tray・再起動（PlatformAdapters.relaunch）を偽物に差し替える。

    デスクトップのセッションは Xorg に固定する（実行する環境の XDG_SESSION_TYPE に頼らない）。
    build_hook を渡すと、build_handlers の偽物が Handlers を返す前に、on_engine_created を渡して呼ぶ（待ち・例外を差し込む）。
    """
    import voice_paste.main as main_module
    from voice_paste.features.transcription import EngineName
    from voice_paste.main import Handlers
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.os_kind import Feature

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    calls: list[str] = []
    build_threads: list[str] = []

    def _record(name: str) -> Callable[..., None]:
        """呼ばれたら name を calls に追加する関数を返す。"""
        return lambda *_args, **_kwargs: calls.append(name)

    session_manager = MagicMock()
    session_manager.close.side_effect = _record("session_manager.close")

    def _build(
        settings: object,
        paths: object,
        notify: object,
        report_progress: object,
        notify_copied: object,
        *,
        adapters: object,
        environ: object,
        unavailable: frozenset[Feature],
        on_engine_created: Callable[[Callable[[], None]], None] = lambda _stop: None,
    ) -> Handlers:
        """配線済みの関数の束を、偽物で作る（外の端末のブラウザの機能を使えない OS では web_api が None）。"""
        build_threads.append(threading.current_thread().name)
        if build_hook is not None:
            build_hook(on_engine_created)
        return Handlers(
            session_manager=session_manager,
            session_api=MagicMock(),
            web_api=None if Feature.WEB_TRANSCRIPTION in unavailable else web_api,
            settings_store=SettingsStore(settings),
            start_local_session=MagicMock(),
            recorder_level=lambda: 0.0,
            stop_engine=_record("stop_engine"),
            active_engine=EngineName.LOCAL_WHISPER,
        )

    web_api = MagicMock()
    build_handlers = MagicMock(side_effect=build_error if build_error is not None else _build)

    runner_class = MagicMock()
    runner_class.return_value.start.return_value = api_started
    runner_class.return_value.stop.side_effect = _record("runner.stop")

    timer_class = MagicMock()
    timer_class.return_value.stop.side_effect = _record("timer.stop")

    hotkey_class = MagicMock()
    hotkey_class.return_value.stop.side_effect = _record("hotkey.stop")
    create_hotkey_listener = MagicMock(return_value=hotkey_class.return_value)

    tray_class = MagicMock()
    tray_class.return_value.hide.side_effect = _record("tray.hide")

    relaunch = MagicMock(side_effect=_record("relaunch"))

    # OS ごとの実装は本物を選び、再起動と、テストが入れた項目だけを偽物に差し替える
    adapter_overrides: dict[str, Any] = {}
    real_select_platform_adapters = main_module.select_platform_adapters

    def _select_platform_adapters(
        os_kind: OsKind, *, lock_file: Path, display_session: DisplaySession
    ) -> object:
        """本物の PlatformAdapters を選び、再起動・ホットキーの受付と差し替え対象の項目を偽物にして返す。"""
        adapters = real_select_platform_adapters(
            os_kind, lock_file=lock_file, display_session=display_session
        )
        return dataclasses.replace(
            adapters,
            relaunch=relaunch,
            create_hotkey_listener=create_hotkey_listener,
            **adapter_overrides,
        )

    # build_ui_deps は本物のまま、作った UiDeps を控える（テストが request_restart などを呼べるように）
    ui_deps: list[UiDeps] = []
    real_build_ui_deps = main_module.build_ui_deps

    def _capture_ui_deps(*args: object, **kwargs: object) -> UiDeps:
        """本物の build_ui_deps で UiDeps を作り、控えて返す。"""
        deps = real_build_ui_deps(*args, **kwargs)
        ui_deps.append(deps)
        return deps

    # build_fastapi は本物のまま、渡された引数を控える
    build_fastapi = MagicMock(side_effect=main_module.build_fastapi)

    monkeypatch.setattr(main_module, "build_handlers", build_handlers)
    monkeypatch.setattr(main_module, "build_fastapi", build_fastapi)
    monkeypatch.setattr(main_module, "ApiServerRunner", runner_class)
    monkeypatch.setattr(main_module, "RepeatingTimer", timer_class)
    monkeypatch.setattr(main_module, "Tray", tray_class)
    monkeypatch.setattr(main_module, "select_platform_adapters", _select_platform_adapters)
    monkeypatch.setattr(main_module, "build_ui_deps", _capture_ui_deps)
    return Wiring(
        calls=calls,
        build_handlers=build_handlers,
        runner_class=runner_class,
        timer_class=timer_class,
        hotkey_class=hotkey_class,
        create_hotkey_listener=create_hotkey_listener,
        tray_class=tray_class,
        relaunch=relaunch,
        build_fastapi=build_fastapi,
        web_api=web_api,
        ui_deps=ui_deps,
        adapter_overrides=adapter_overrides,
        build_threads=build_threads,
    )


def wait_for_startup(app: QApplication, wiring: Wiring) -> None:
    """配線の結果を受けて起動を終えるまで（上限は STARTUP_WAIT_SEC）、イベントを処理する。"""
    deadline = time.monotonic() + STARTUP_WAIT_SEC
    while not wiring.startup_finished and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(POLL_INTERVAL_SEC)
    app.processEvents()


def process_events_for(app: QApplication, seconds: float) -> None:
    """指定した秒数の間、イベントを処理し続ける。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(POLL_INTERVAL_SEC)


def emit_connected(signal_mock: MagicMock) -> None:
    """偽物の Signal に connect されたまま（disconnect されていない）の受け手を、つないだ順に呼ぶ。"""
    disconnected = [c.args[0] for c in signal_mock.disconnect.call_args_list]
    for connected in signal_mock.connect.call_args_list:
        if connected.args[0] not in disconnected:
            connected.args[0]()


@dataclass
class BlockingBuild:
    """配線の偽物の差し込み。止める関数を on_engine_created に渡し、それが呼ばれるまで戻らず、呼ばれたら StartupError を送出する。"""

    stop_engine: MagicMock
    """on_engine_created に渡す、エンジンを止める関数。"""
    registered: threading.Event
    """止める関数を on_engine_created に渡したら立つ。"""
    stopped: threading.Event
    """止める関数が呼ばれたら立つ。"""

    @classmethod
    def create(cls) -> BlockingBuild:
        """止める関数が呼ばれたら stopped を立てる差し込みを作る。"""
        stopped = threading.Event()
        return cls(
            stop_engine=MagicMock(side_effect=lambda: stopped.set()),
            registered=threading.Event(),
            stopped=stopped,
        )

    def __call__(self, on_engine_created: Callable[[Callable[[], None]], None]) -> NoReturn:
        """止める関数を渡し、呼ばれるまで（上限は BUILD_WAIT_SEC）待ってから StartupError を送出する。"""
        on_engine_created(self.stop_engine)
        self.registered.set()
        self.stopped.wait(BUILD_WAIT_SEC)
        raise StartupError("文字起こしワーカーを止めた")


def timer_interval(timer_call: Any) -> float:
    """RepeatingTimer を作った呼び出しから、呼ぶ間隔（秒）を取り出す。"""
    if len(timer_call.args) > 1:
        return timer_call.args[1]
    return timer_call.kwargs["interval_sec"]


def record_lock_release(monkeypatch: pytest.MonkeyPatch, wiring: Wiring) -> None:
    """SingleInstanceLock.release が呼ばれたことを、止める操作の記録（wiring.calls）へ追加する。本物の release も呼ぶ。"""
    from voice_paste.runtime.single_instance import SingleInstanceLock

    original_release = SingleInstanceLock.release

    def _release(self: SingleInstanceLock) -> None:
        """記録してから本物の release を呼ぶ。"""
        wiring.calls.append("lock.release")
        original_release(self)

    monkeypatch.setattr(SingleInstanceLock, "release", _release)


def record_about_to_quit_threads(app: QApplication) -> tuple[list[bool], Callable[[], None]]:
    """QApplication.aboutToQuit を受けたスレッドが、メインスレッドだったか（受けた順）を控える。控えの一覧と、受けるのをやめる関数を返す。

    invokeMethod は C++ の quit スロットを直に呼ぶため、Python の属性に差し替えた quit は呼ばれない。
    quit がイベントループを抜けさせるときに出る aboutToQuit は、quit を呼んだスレッドでなく、ループを回すスレッドで受ける。
    """
    on_main_thread: list[bool] = []

    def _on_about_to_quit() -> None:
        """受けたスレッドがメインスレッドかを控える。"""
        on_main_thread.append(threading.current_thread() is threading.main_thread())

    app.aboutToQuit.connect(_on_about_to_quit)
    return on_main_thread, lambda: app.aboutToQuit.disconnect(_on_about_to_quit)


def make_exec_loop_with_quit_request(
    lock: MagicMock, gave_up: list[bool], wiring: Wiring
) -> Callable[[QApplication], int]:
    """起動を終えた後に別のスレッドから終了を頼まれてから、本物のイベントループを回す exec_loop を作る。

    頼みが効かずにループが抜けないときのために、上限で諦めて抜け、gave_up に True を追加する。
    """

    def _exec_loop(app: QApplication) -> int:
        """起動を終えるまで待ち、on_quit_requested に渡された関数を別のスレッドから呼び、ループを回す。"""
        wait_for_startup(app, wiring)
        on_quit = lock.on_quit_requested.call_args.args[0]
        thread = threading.Thread(target=on_quit)
        thread.start()
        thread.join()

        def _give_up() -> None:
            """上限まで抜けなかったことを控えて、ループを抜ける。"""
            gave_up.append(True)
            app.quit()

        give_up_timer = QTimer()
        give_up_timer.setSingleShot(True)
        give_up_timer.timeout.connect(_give_up)
        give_up_timer.start(QUIT_LOOP_TIMEOUT_MS)
        exit_code = app.exec()
        give_up_timer.stop()
        return exit_code

    return _exec_loop


# === parse_args ===


def test_parse_args() -> None:
    """データの置き場所だけを読む（正常系）。"""
    from voice_paste.main import CliArgs, parse_args

    # 実行
    args = parse_args(["--data-dir", "C:/tmp/vp"])

    # 検証
    assert args == CliArgs(data_dir=Path("C:/tmp/vp"))


def test_parse_args_when_no_data_dir() -> None:
    """データの置き場所が無ければ既定の置き場所にする（正常系）。"""
    from voice_paste.main import CliArgs, parse_args

    # 実行
    args = parse_args([])

    # 検証
    assert args == CliArgs(data_dir=None)


def test_parse_args_when_unknown_argument() -> None:
    """知らない引数なら終わる（異常系）。"""
    from voice_paste.main import parse_args

    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--unknown"])
    assert exc_info.value.code == 2


# === main ===


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Win32 の排他（SingleInstanceLock と background_acquire）で確かめるため Windows でだけ流す",
)
def test_main(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    background_acquire: Callable[[str, float], BackgroundAcquire],
) -> None:
    """設定を読んで API・ホットキー・トレイを立て、イベントループが抜けたら片付けて 0 を返す（正常系）。"""
    from voice_paste.main import (
        PURGE_INTERVAL_SEC,
        SESSION_LIMIT_CHECK_INTERVAL_SEC,
        main,
    )
    from voice_paste.runtime.single_instance import instance_name

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    record_lock_release(monkeypatch, wiring)

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)
    reacquired = background_acquire(instance_name(data_dir), SHORT_ACQUIRE_TIMEOUT_SEC)
    reacquired_decided = reacquired.wait(ACQUIRE_WAIT_SEC)

    # 検証
    assert exit_code == 0
    assert wiring.build_handlers.call_args.kwargs["environ"] is os.environ
    assert not (data_dir / "settings.yaml").exists()
    assert (data_dir / "api_token").exists()
    assert wiring.build_handlers.call_args.kwargs["unavailable"] == frozenset()
    wiring.create_hotkey_listener.assert_called_once()
    assert set(wiring.hotkey.start.call_args.args[0]) == DEFAULT_HOTKEYS
    assert [timer_interval(c) for c in wiring.timer_class.call_args_list] == [
        SESSION_LIMIT_CHECK_INTERVAL_SEC,
        PURGE_INTERVAL_SEC,
    ]
    assert wiring.calls == [
        "hotkey.stop",
        "timer.stop",
        "timer.stop",
        "runner.stop",
        "session_manager.close",
        "stop_engine",
        "tray.hide",
        "lock.release",
    ]
    assert reacquired_decided
    assert reacquired.error is None


def test_main_when_building_off_main_thread(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """配線をメインスレッドの外で流し、その間もイベントループを回す（正常系）。"""
    from voice_paste.main import main
    from voice_paste.ui.tray import TrayState

    # 準備: 配線の偽物は release が立つまで戻らない
    release = threading.Event()
    wiring = install_wiring(
        monkeypatch, qapp, build_hook=lambda _on_engine_created: release.wait(BUILD_WAIT_SEC)
    )
    set_state_before_release: list[Any] = []
    hotkey_started_before_release: list[bool] = []

    def _exec_loop(app: QApplication) -> int:
        """配線の間もイベントを処理し、トレイが準備中のままかを控えてから配線を戻し、起動を終えるまで処理する。"""
        process_events_for(app, SETTLE_SEC)
        set_state_before_release.extend(wiring.tray.set_state.call_args_list)
        hotkey_started_before_release.append(wiring.hotkey.start.called)
        release.set()
        wait_for_startup(app, wiring)
        return 0

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=_exec_loop)

    # 検証
    assert exit_code == 0
    assert wiring.build_threads == ["startup-build"]
    assert set_state_before_release == [call(TrayState.STARTING, busy=False)]
    assert hotkey_started_before_release == [False]
    assert call(TrayState.IDLE, busy=False) in wiring.tray.set_state.call_args_list
    wiring.hotkey.start.assert_called_once()


def test_main_when_quit_while_building(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """配線の間に終了を頼まれたら、エンジンを止めて排他を放す（正常系）。"""
    from voice_paste.main import main

    # 準備: 配線の偽物は止める関数を渡した後、それが呼ばれるまで戻らない（呼ばれたら StartupError）
    blocking_build = BlockingBuild.create()
    wiring = install_wiring(monkeypatch, qapp, build_hook=blocking_build)
    lock = MagicMock()
    lock.release.side_effect = lambda: wiring.calls.append("lock.release")
    wiring.adapter_overrides["acquire_single_instance"] = MagicMock(return_value=lock)

    def _exec_loop(app: QApplication) -> int:
        """止める関数が渡るのを待ってから、トレイの「終了」を送出し、イベントを処理して抜ける。"""
        blocking_build.registered.wait(BUILD_WAIT_SEC)
        emit_connected(wiring.tray.quit_requested)
        app.processEvents()
        return 0

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=_exec_loop)

    # 検証
    assert exit_code == 0
    blocking_build.stop_engine.assert_called_once()
    wiring.create_hotkey_listener.assert_not_called()
    wiring.runner_class.assert_not_called()
    wiring.tray.show_failure.assert_not_called()
    assert wiring.calls[-2:] == ["tray.hide", "lock.release"]
    wiring.relaunch.assert_not_called()


def test_main_when_restart_while_building(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """配線の間に再起動を頼まれたら、エンジンを止めてから起動し直す（正常系）。"""
    from voice_paste.main import main

    # 準備: 配線の偽物は止める関数を渡した後、それが呼ばれるまで戻らない（呼ばれたら StartupError）
    blocking_build = BlockingBuild.create()
    wiring = install_wiring(monkeypatch, qapp, build_hook=blocking_build)
    lock = MagicMock()
    lock.release.side_effect = lambda: wiring.calls.append("lock.release")
    wiring.adapter_overrides["acquire_single_instance"] = MagicMock(return_value=lock)

    def _exec_loop(app: QApplication) -> int:
        """止める関数が渡るのを待ってから、トレイの「再起動」を送出し、イベントを処理して抜ける。"""
        blocking_build.registered.wait(BUILD_WAIT_SEC)
        emit_connected(wiring.tray.restart_requested)
        app.processEvents()
        return 0

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=_exec_loop)

    # 検証
    assert exit_code == 0
    blocking_build.stop_engine.assert_called_once()
    wiring.relaunch.assert_called_once()
    assert wiring.calls.index("relaunch") > wiring.calls.index("lock.release")


def test_main_when_invalid_settings(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """設定が合わなければトレイで知らせて入口を立てない（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    (data_dir / "settings.yaml").write_text(
        "transcription:\n  local_whisper:\n    beam_size: x\n", encoding="utf-8"
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    wiring.tray.set_failed.assert_called_once_with(settings_enabled=False)
    wiring.tray.show_failure.assert_called_once()
    assert wiring.tray.show_failure.call_args.args[0] == "settings_invalid"
    assert "transcription.local_whisper.beam_size" in wiring.tray.show_failure.call_args.args[1]
    assert wiring.tray.show_failure.call_args.kwargs == {"paths": (data_dir / "settings.yaml",)}
    assert "transcription.local_whisper.beam_size" in str(
        read_log_records(data_dir / "log", "ERROR")
    )
    wiring.build_handlers.assert_not_called()
    wiring.runner_class.assert_not_called()
    wiring.hotkey.start.assert_not_called()


def test_main_when_startup_error(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """エンジンを準備できなければトレイを失敗にして続ける（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(
        monkeypatch, qapp, build_error=StartupError("文字起こしのエンジンを準備できない")
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    wiring.tray.set_failed.assert_called_once_with(settings_enabled=True)
    assert [c.args[0] for c in wiring.tray.show_failure.call_args_list] == ["engine_unavailable"]
    wiring.runner_class.assert_not_called()
    wiring.hotkey.start.assert_not_called()


def test_main_when_api_unavailable(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    default_settings: Settings,
) -> None:
    """待ち受けを始められなければトークンのファイルを書かずに知らせて続ける（正常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp, api_started=False)
    token_file = data_dir / "api_token"
    previous_content = '{"port": 1, "token": "previous-token"}'
    token_file.write_text(previous_content, encoding="utf-8")

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    assert token_file.read_text(encoding="utf-8") == previous_content
    assert [c.args for c in wiring.tray.show_failure.call_args_list] == [
        ("api_unavailable", f"ポート {default_settings.api.port} で待ち受けを始められません")
    ]
    wiring.hotkey.start.assert_called_once()


def test_main_when_restart_requested(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """再起動を頼まれたら片付けた後に起動し直す（正常系）。"""
    from voice_paste.main import main

    # 準備: イベントループの中で、画面の再起動の依頼（UiDeps.request_restart）を呼ぶ
    wiring = install_wiring(monkeypatch, qapp)

    def _request_restart(app: QApplication) -> int:
        """起動を終えるまで待ち、UiDeps.request_restart を呼んで 0 を返す。"""
        wait_for_startup(app, wiring)
        wiring.ui_deps[0].request_restart()
        return 0

    argv = ["--data-dir", str(data_dir)]

    # 実行
    exit_code = main(argv, exec_loop=_request_restart)

    # 検証: 再起動は、API とエンジンを止めた後に 1 回だけ
    assert exit_code == 0
    wiring.relaunch.assert_called_once_with(argv)
    assert wiring.calls.index("relaunch") > wiring.calls.index("runner.stop")
    assert wiring.calls.index("relaunch") > wiring.calls.index("stop_engine")


def test_main_when_no_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """データの置き場所を渡さなければ既定の置き場所で起動する（正常系）。"""
    import voice_paste.main as main_module
    import voice_paste.shared.constants as constants_module
    from voice_paste.main import main

    # 準備: platformdirs の置き場所を一時フォルダの config・local へ、checkout の上書きを一時フォルダの checkout の下へ向ける
    config_dir = tmp_path / "config"
    local_dir = tmp_path / "local"
    local_settings_file = tmp_path / "checkout" / "settings.local.yaml"
    wiring = install_wiring(monkeypatch, qapp)
    monkeypatch.setattr(constants_module, "user_config_dir", lambda *_a, **_k: str(config_dir))
    monkeypatch.setattr(constants_module, "user_data_dir", lambda *_a, **_k: str(local_dir))
    resolve_app_paths = constants_module.resolve_app_paths
    monkeypatch.setattr(
        main_module,
        "resolve_app_paths",
        lambda data_dir: dataclasses.replace(
            resolve_app_paths(data_dir), local_settings_file=local_settings_file
        ),
    )

    # 実行
    exit_code = main([], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    assert not (config_dir / "settings.yaml").exists()
    assert (local_dir / "api_token").exists()
    assert list((local_dir / "log").glob("*.log"))


def test_main_when_previous_instance_not_released(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """前のプロセスが排他を放さなければトレイを出さずに終わる（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    wiring.adapter_overrides["acquire_single_instance"] = MagicMock(
        side_effect=StartupError("前の常駐サービスが終わらない")
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 1
    assert len(read_log_records(data_dir / "log", "ERROR")) == 1
    wiring.tray_class.assert_not_called()
    wiring.build_handlers.assert_not_called()


def test_main_when_quit_requested(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """後から起動したプロセスに頼まれたら片付けて排他を放す（正常系）。"""
    from voice_paste.main import main

    # 準備: 排他は偽物（SingleInstanceLock の代わり）を返し、放したことを止める操作の記録へ追加する
    wiring = install_wiring(monkeypatch, qapp)
    lock = MagicMock()
    lock.release.side_effect = lambda: wiring.calls.append("lock.release")
    wiring.adapter_overrides["acquire_single_instance"] = MagicMock(return_value=lock)
    gave_up: list[bool] = []
    about_to_quit_on_main_thread, stop_recording_quit = record_about_to_quit_threads(qapp)
    exec_loop = make_exec_loop_with_quit_request(lock, gave_up, wiring)

    # 実行
    try:
        exit_code = main(["--data-dir", str(data_dir)], exec_loop=exec_loop)
    finally:
        stop_recording_quit()

    # 検証: 頼みでイベントループが抜け（上限で諦めていない）、quit がメインスレッドで 1 回だけ効き、
    # 止めた後に排他を 1 回だけ放し、起動し直さない
    assert exit_code == 0
    assert gave_up == []
    assert about_to_quit_on_main_thread == [True]
    assert wiring.calls == [
        "hotkey.stop",
        "timer.stop",
        "timer.stop",
        "runner.stop",
        "session_manager.close",
        "stop_engine",
        "tray.hide",
        "lock.release",
    ]
    wiring.relaunch.assert_not_called()


@pytest.mark.skipif(
    sys.platform == "win32", reason="SIGTERM をシグナルで受ける動きを確かめるため Windows では流さない"
)
def test_main_when_sigterm(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """SIGTERM を受けたら片付けて排他を放す（正常系）。"""
    from voice_paste.main import main

    # 準備: main が SIGTERM のハンドラを入れなければ、テストのプロセスが終わらないよう、控えるだけのハンドラを先に入れる
    wiring = install_wiring(monkeypatch, qapp)
    lock = MagicMock()
    lock.release.side_effect = lambda: wiring.calls.append("lock.release")
    wiring.adapter_overrides["acquire_single_instance"] = MagicMock(return_value=lock)
    received_without_main_handler: list[bool] = []
    signal.signal(signal.SIGTERM, lambda *_args: received_without_main_handler.append(True))
    quit_app = MagicMock()
    monkeypatch.setattr(qapp, "quit", quit_app)

    def _send_sigterm(app: QApplication) -> int:
        """起動を終えるまで待ち、自分のプロセスへ SIGTERM を送り、溜まったイベントを処理して 0 を返す。"""
        wait_for_startup(app, wiring)
        signal.raise_signal(signal.SIGTERM)
        app.processEvents()
        return 0

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=_send_sigterm)

    # 検証: main のハンドラが QApplication.quit を呼び、止めた後に排他を放す
    assert exit_code == 0
    assert received_without_main_handler == []
    quit_app.assert_called_once()
    assert wiring.calls.count("hotkey.stop") == 1
    assert wiring.calls.count("tray.hide") == 1
    assert wiring.calls[-1] == "lock.release"


def test_main_when_key_sender_unavailable(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """キーの送信の機器を開けなければトレイで知らせて続ける（異常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.errors import DeliveryError
    from voice_paste.ui.tray import TrayState

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    close_key_sender = MagicMock()
    wiring.adapter_overrides["open_key_sender"] = MagicMock(
        side_effect=DeliveryError("Permission denied")
    )
    wiring.adapter_overrides["close_key_sender"] = close_key_sender

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    assert [c.args for c in wiring.tray.show_failure.call_args_list] == [
        ("paste_unavailable", "Permission denied")
    ]
    wiring.hotkey.start.assert_called_once()
    assert wiring.tray.set_state.call_args == call(TrayState.IDLE, busy=False)
    close_key_sender.assert_called_once()


def test_main_when_engine_fallback(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """配線の間の知らせをトレイの通知で出す（正常系）。"""
    from voice_paste.main import main

    # 準備（配線の間に notify を呼ぶ）
    message = "Haas のサーバーへ接続できないため、ローカルの Whisper で起こします。"

    def build_hook(_register_stop: Callable[[Callable[[], None]], None]) -> None:
        """配線の関数が受けた notify へ切り戻しを渡す。"""
        wiring.build_handlers.call_args.args[2]("engine_fallback", message)

    wiring = install_wiring(monkeypatch, qapp, build_hook=build_hook)

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    wiring.tray.show_failure.assert_called_once_with("engine_fallback", message)


def test_main_when_web_transcription_unavailable(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """外の端末のブラウザの機能を使えない OS ではキューを始めず、/web/ のルートを持たない（正常系）。"""
    import voice_paste.main as main_module
    from voice_paste.main import main
    from voice_paste.shared.os_kind import Feature

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    monkeypatch.setattr(
        main_module, "unavailable_features", lambda _os_kind: frozenset({Feature.WEB_TRANSCRIPTION})
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    assert wiring.build_handlers.call_args.kwargs["unavailable"] == frozenset(
        {Feature.WEB_TRANSCRIPTION}
    )
    assert wiring.build_fastapi.call_args.kwargs["web_api"] is None
    wiring.web_api.queue.start.assert_not_called()
    wiring.web_api.queue.close.assert_not_called()


@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        pytest.param(None, "xcb", id="unset"),
        pytest.param("offscreen", "offscreen", id="preset"),
    ],
)
def test_main_when_qt_platform(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    initial: str | None,
    expected: str,
) -> None:
    """Wayland のセッションでは Qt のプラットフォームを xcb にする。先に入れた値があれば変えない（正常系）。"""
    import voice_paste.main as main_module
    from voice_paste.main import main

    # 準備: QApplication を作る時点の QT_QPA_PLATFORM を控える（生成は共有の qapp を返す）
    wiring = install_wiring(monkeypatch, qapp)
    wiring.adapter_overrides["qt_platform"] = "xcb"
    platform_at_creation: list[str | None] = []

    class RecordingApplication:
        """QApplication の代わり。既存のインスタンスは無いとし、作られた時点の QT_QPA_PLATFORM を控えて共有の qapp を返す。"""

        @staticmethod
        def instance() -> None:
            """既存のインスタンスは無い。"""
            return None

        def __new__(cls, _argv: list[str]) -> QApplication:  # type: ignore[misc]
            """作られた時点の環境変数を控え、共有の qapp を返す。"""
            platform_at_creation.append(os.environ.get("QT_QPA_PLATFORM"))
            return qapp

    monkeypatch.setattr(main_module, "QApplication", RecordingApplication)
    if initial is None:
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    else:
        monkeypatch.setenv("QT_QPA_PLATFORM", initial)

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=wiring.exit_after_startup)

    # 検証
    assert exit_code == 0
    assert platform_at_creation == [expected]


# === _StartupBuild ===


@dataclass
class StartupBuildProbe:
    """_StartupBuild の done で受けた結果と、build が呼ばれたスレッドの控え。"""

    received: list[object]
    """done で受けた結果（受けた順）。"""
    threads: list[threading.Thread]
    """build が呼ばれたスレッド（呼ばれた順）。"""
    started: threading.Event
    """build が呼ばれたら立つ。"""


@pytest.fixture
def startup_probe() -> StartupBuildProbe:
    """_StartupBuild の結果とスレッドを控える入れ物を返す。"""
    return StartupBuildProbe(received=[], threads=[], started=threading.Event())


def _make_startup_build(probe: StartupBuildProbe) -> Any:
    """done を probe.received へつないだ _StartupBuild を作る。"""
    from voice_paste.main import _StartupBuild

    startup = _StartupBuild()
    startup.done.connect(lambda result: probe.received.append(result))
    return startup


def _record_thread(probe: StartupBuildProbe) -> None:
    """build を呼んだスレッドを控え、started を立てる。"""
    probe.threads.append(threading.current_thread())
    probe.started.set()


def _wait_received(app: QApplication, probe: StartupBuildProbe) -> None:
    """done で結果を受けるまで（上限は STARTUP_WAIT_SEC）イベントを処理し、その後も SETTLE_SEC だけ処理を続ける。"""
    deadline = time.monotonic() + STARTUP_WAIT_SEC
    while not probe.received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(POLL_INTERVAL_SEC)
    process_events_for(app, SETTLE_SEC)


def test_start(qapp: QApplication, startup_probe: StartupBuildProbe) -> None:
    """配線の結果を done で渡す（正常系）。"""
    # 準備
    handlers = MagicMock()

    def _build(_register_stop: Callable[[Callable[[], None]], None]) -> object:
        """呼ばれたスレッドを控えて Handlers を返す。"""
        _record_thread(startup_probe)
        return handlers

    startup = _make_startup_build(startup_probe)

    # 実行
    startup.start(_build)
    _wait_received(qapp, startup_probe)

    # 検証
    assert startup_probe.received == [handlers]
    assert [thread.name for thread in startup_probe.threads] == ["startup-build"]


def test_start_when_startup_error(qapp: QApplication, startup_probe: StartupBuildProbe) -> None:
    """配線の失敗を done で渡す（正常系）。"""
    # 準備
    error = StartupError("文字起こしのエンジンを準備できない")

    def _build(_register_stop: Callable[[Callable[[], None]], None]) -> object:
        """StartupError を送出する。"""
        raise error

    startup = _make_startup_build(startup_probe)

    # 実行
    startup.start(_build)
    _wait_received(qapp, startup_probe)

    # 検証
    assert startup_probe.received == [error]


def test_start_when_unexpected_error(
    qapp: QApplication, startup_probe: StartupBuildProbe, caplog: pytest.LogCaptureFixture
) -> None:
    """想定外の例外も StartupError にして done で渡す（異常系）。"""

    # 準備
    def _build(_register_stop: Callable[[Callable[[], None]], None]) -> object:
        """RuntimeError を送出する。"""
        raise RuntimeError("配線の不具合")

    startup = _make_startup_build(startup_probe)
    caplog.set_level(logging.ERROR)

    # 実行
    startup.start(_build)
    _wait_received(qapp, startup_probe)

    # 検証
    assert [type(result) for result in startup_probe.received] == [StartupError]
    assert [record.levelno for record in caplog.records] == [logging.ERROR]


def test_cancel(qapp: QApplication, startup_probe: StartupBuildProbe) -> None:
    """控えた関数でエンジンを止め、done を送出しない（正常系）。"""
    # 準備: build は止める関数を控えた後、それが呼ばれるまで待ってから StartupError を送出する
    blocking_build = BlockingBuild.create()

    def _build(register_stop: Callable[[Callable[[], None]], None]) -> NoReturn:
        """呼ばれたスレッドを控え、止める関数を控えて、呼ばれるまで待つ。"""
        _record_thread(startup_probe)
        blocking_build(register_stop)

    startup = _make_startup_build(startup_probe)
    startup.start(_build)
    blocking_build.registered.wait(BUILD_WAIT_SEC)

    # 実行
    startup.cancel(1.0)

    # 検証
    blocking_build.stop_engine.assert_called_once()
    assert not startup_probe.threads[0].is_alive()
    process_events_for(qapp, SETTLE_SEC)
    assert startup_probe.received == []


def test_cancel_when_not_registered(qapp: QApplication, startup_probe: StartupBuildProbe) -> None:
    """控える前に取り消されたら、控えたときに止める（正常系）。"""
    # 準備: build は gate が立つまで待ってから止める関数を控え、Handlers を返す
    gate = threading.Event()
    stop_engine = MagicMock()
    handlers = MagicMock()

    def _build(register_stop: Callable[[Callable[[], None]], None]) -> object:
        """gate が立つまで待ち、止める関数を控えて Handlers を返す。"""
        _record_thread(startup_probe)
        gate.wait(BUILD_WAIT_SEC)
        register_stop(stop_engine)
        return handlers

    startup = _make_startup_build(startup_probe)
    startup.start(_build)
    startup_probe.started.wait(BUILD_WAIT_SEC)

    # 実行
    startup.cancel(0.01)
    gate.set()
    startup_probe.threads[0].join(BUILD_WAIT_SEC)

    # 検証
    stop_engine.assert_called_once()
    handlers.stop_engine.assert_called_once()
    process_events_for(qapp, SETTLE_SEC)
    assert startup_probe.received == []


def test_cancel_when_thread_not_finished(
    qapp: QApplication, startup_probe: StartupBuildProbe, caplog: pytest.LogCaptureFixture
) -> None:
    """スレッドが終わらなければ待つのをやめて戻る（異常系）。"""
    # 準備: build は止める関数を控えた後、hold が立つまで待ち続ける（止める関数では戻らない）
    registered = threading.Event()
    hold = threading.Event()

    def _build(register_stop: Callable[[Callable[[], None]], None]) -> object:
        """止める関数を控え、hold が立つまで待つ。"""
        register_stop(MagicMock())
        registered.set()
        hold.wait(BUILD_WAIT_SEC)
        return MagicMock()

    startup = _make_startup_build(startup_probe)
    startup.start(_build)
    registered.wait(BUILD_WAIT_SEC)
    caplog.set_level(logging.WARNING)

    # 実行
    started_at = time.monotonic()
    startup.cancel(0.05)
    elapsed = time.monotonic() - started_at
    hold.set()

    # 検証
    assert elapsed < 1.0
    assert [record.levelno for record in caplog.records] == [logging.WARNING]


# === select_platform_adapters ===


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 専用の実装を読み込むため Linux では流さない")
def test_select_platform_adapters_when_windows(tmp_path: Path) -> None:
    """Windows は pycaw の音量・Edge・Win32 の排他を選ぶ（正常系）。"""
    import subprocess

    from voice_paste.integrations.browser.opener import open_app_window
    from voice_paste.integrations.keyboard.sender import send_enter, send_paste
    from voice_paste.integrations.volume.adapter import lower_volume, restore_volume
    from voice_paste.main import select_platform_adapters
    from voice_paste.runtime.hotkey import HotkeyListener
    from voice_paste.runtime.single_instance import acquire_single_instance
    from voice_paste.shared.os_kind import DisplaySession, OsKind

    # 実行
    adapters = select_platform_adapters(
        OsKind.WINDOWS, lock_file=tmp_path / "instance.lock", display_session=DisplaySession.X11
    )

    # 検証
    assert adapters.lower_volume is lower_volume
    assert adapters.restore_volume is restore_volume
    assert adapters.open_app_window is open_app_window
    assert adapters.acquire_single_instance is acquire_single_instance
    assert adapters.send_paste is send_paste
    assert adapters.worker_creationflags == subprocess.CREATE_NO_WINDOW
    assert adapters.send_enter is send_enter
    assert isinstance(adapters.create_hotkey_listener("name", MagicMock()), HotkeyListener)
    assert adapters.qt_platform is None


@pytest.mark.skipif(sys.platform == "win32", reason="Linux 専用の実装を読み込むため Windows では流さない")
def test_select_platform_adapters_when_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux の Xorg のセッションは何もしない音量・Chromium 系・flock の排他・XTEST の貼り付けを選ぶ（正常系）。"""
    from voice_paste.integrations.browser.opener_linux import open_app_window_linux
    from voice_paste.integrations.keyboard.sender import send_enter
    from voice_paste.integrations.keyboard.sender_linux import send_paste_linux
    from voice_paste.main import select_platform_adapters
    from voice_paste.runtime.hotkey import HotkeyListener, validate_hotkeys
    from voice_paste.runtime.single_instance_linux import acquire_single_instance_linux
    from voice_paste.shared.os_kind import DisplaySession, OsKind

    # 準備: 他のテストが読み込み済みでも、選ぶときに読み込まれないことを確かめられるよう、Wayland のモジュールを読み込み済みでない状態にする
    lock_file = tmp_path / "instance.lock"
    monkeypatch.delitem(sys.modules, "voice_paste.integrations.keyboard.sender_wayland", raising=False)

    # 実行
    adapters = select_platform_adapters(
        OsKind.LINUX, lock_file=lock_file, display_session=DisplaySession.X11
    )

    # 検証
    assert adapters.lower_volume is None
    assert adapters.restore_volume is None
    assert adapters.validate_hotkeys is validate_hotkeys
    assert adapters.open_app_window is open_app_window_linux
    assert adapters.send_paste is send_paste_linux
    assert isinstance(adapters.acquire_single_instance, functools.partial)
    assert adapters.acquire_single_instance.func is acquire_single_instance_linux
    assert adapters.acquire_single_instance.keywords == {"lock_file": lock_file}
    assert adapters.worker_creationflags == 0
    assert "voice_paste.integrations.volume.adapter" not in sys.modules
    assert adapters.send_enter is send_enter
    assert isinstance(adapters.create_hotkey_listener("name", MagicMock()), HotkeyListener)
    assert adapters.qt_platform is None
    assert "voice_paste.integrations.keyboard.sender_wayland" not in sys.modules


@pytest.mark.skipif(sys.platform == "win32", reason="Linux 専用の実装を読み込むため Windows では流さない")
def test_select_platform_adapters_when_wayland(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wayland のセッションは uinput のキーの送信・GNOME のショートカット・xcb を選ぶ（正常系）。"""
    import evdev

    from voice_paste.main import select_platform_adapters
    from voice_paste.runtime.hotkey_gnome import GnomeShortcutListener, validate_gnome_hotkeys
    from voice_paste.shared.os_kind import DisplaySession, OsKind

    # 準備: pyperclip の書き先の指定と UInput の生成を偽物にし、sender_linux を読み込み済みでない状態にする
    set_clipboard = MagicMock()
    uinput_class = MagicMock()
    monkeypatch.setattr("pyperclip.set_clipboard", set_clipboard)
    monkeypatch.setattr(evdev, "UInput", uinput_class)
    monkeypatch.delitem(sys.modules, "voice_paste.integrations.keyboard.sender_linux", raising=False)

    # 実行
    adapters = select_platform_adapters(
        OsKind.LINUX, lock_file=tmp_path / "instance.lock", display_session=DisplaySession.WAYLAND
    )

    # 検証: キーの送信は同じ UInputKeyboard のメソッドで、開く前は UInput を作らない
    assert adapters.send_paste.__self__ is adapters.send_enter.__self__
    assert adapters.open_key_sender.__self__ is adapters.send_enter.__self__
    assert adapters.close_key_sender.__self__ is adapters.send_enter.__self__
    uinput_class.assert_not_called()
    assert isinstance(adapters.create_hotkey_listener("name", MagicMock()), GnomeShortcutListener)
    assert adapters.qt_platform == "xcb"
    assert adapters.validate_hotkeys is validate_gnome_hotkeys
    set_clipboard.assert_called_once_with("xclip")
    assert "voice_paste.integrations.keyboard.sender_linux" not in sys.modules


# === start_local_session ===


def test_start_local_session_when_busy() -> None:
    """処理中なら busy を知らせる（正常系）。"""
    from voice_paste.main import start_local_session
    from voice_paste.shared.errors import SessionBusyError

    # 準備
    session_manager = MagicMock()
    session_manager.start.side_effect = SessionBusyError("処理中")
    notify = MagicMock()

    # 実行
    start_local_session("hotkey", session_manager=session_manager, notify=notify)

    # 検証
    assert [c.args[0] for c in notify.call_args_list] == ["busy"]


def test_start_local_session_when_microphone_unavailable() -> None:
    """マイクを開けなければ microphone_unavailable を知らせる（正常系）。"""
    from voice_paste.main import start_local_session
    from voice_paste.shared.errors import MicrophoneUnavailableError

    # 準備
    session_manager = MagicMock()
    session_manager.start.side_effect = MicrophoneUnavailableError("マイクを開けない")
    notify = MagicMock()

    # 実行
    start_local_session("tray", session_manager=session_manager, notify=notify)

    # 検証
    assert [c.args[0] for c in notify.call_args_list] == ["microphone_unavailable"]


def test_start_local_session_when_unexpected_error(caplog: pytest.LogCaptureFixture) -> None:
    """想定外の例外も漏らさない（正常系）。"""
    from voice_paste.main import start_local_session

    # 準備
    caplog.set_level(logging.ERROR)
    session_manager = MagicMock()
    session_manager.start.side_effect = RuntimeError("想定外")

    # 実行
    start_local_session("hotkey", session_manager=session_manager, notify=MagicMock())

    # 検証
    assert len([record for record in caplog.records if record.levelno == logging.ERROR]) == 1


# === _wire_outputs ===


def _install_adapters(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """main が出力先・プリセットの種類へ渡す外部連携と time.sleep を偽物に差し替え、呼ばれた順を持つ親の Mock を返す。

    親の `copy_to_clipboard`・`send_paste`・`send_enter`・`open_app_window`・`post_json`・`sleep` がそれぞれの偽物。
    `open_app_window`・`send_paste` は main が OS ごとの実装として受け取るため、差し替えず、テストが `open_window`・`send_paste` に渡す。
    `post_json` は 200 を返す。
    """
    import voice_paste.main as main_module
    from voice_paste.integrations.http.types import PostResult

    adapters = MagicMock()
    adapters.post_json.return_value = PostResult(status=200, retry_after_sec=None)
    monkeypatch.setattr(main_module, "copy_to_clipboard", adapters.copy_to_clipboard)
    monkeypatch.setattr(main_module, "send_enter", adapters.send_enter)
    monkeypatch.setattr(main_module, "post_json", adapters.post_json)
    monkeypatch.setattr("time.sleep", adapters.sleep)
    return adapters


def _outputs_by_id(wired: tuple[OutputSpec, ...]) -> dict[str, OutputSpec]:
    """配線した出力先の一覧を、出力先の ID で引ける dict にする。"""
    return {spec.id: spec for spec in wired}


def _kinds_by_name(wired: tuple[PresetKindSpec, ...]) -> dict[str, PresetKindSpec]:
    """配線したプリセットの種類の一覧を、種類で引ける dict にする。"""
    return {spec.kind: spec for spec in wired}


def _outcome() -> TranscriptionOutcome:
    """届ける結果（起こした文字「テスト」）を作る。"""
    from voice_paste.shared.types import TranscriptionOutcome as OutcomeModel

    return OutcomeModel(session_id="session-1", result="transcribed", text="テスト", error=None)


def _make_output_deps(adapters: MagicMock, get_settings: Callable[[], Settings]) -> OutputDeps:
    """外部連携を adapters の偽物にした OutputDeps を作る。paste は呼ぶたびに今の設定の paste_key で send_paste を呼ぶ。"""
    from voice_paste.features.outputs.types import OutputDeps as OutputDepsModel

    return OutputDepsModel(
        copy=adapters.copy_to_clipboard,
        paste=lambda: adapters.send_paste(get_settings().keyboard.paste_key),
        send_enter=adapters.send_enter,
        sleep=adapters.sleep,
        jitter=adapters.jitter,
        post=adapters.post_json,
        get_settings=get_settings,
        notify_copied=adapters.notify_copied,
    )


def _trial_handler(
    outcome: TranscriptionOutcome, target: str | None, *, copy: Callable[[str], None]
) -> None:
    """試しの出力先の届ける関数。起こした文字をクリップボードへ書くだけ。"""
    copy(outcome.text)


def test_wire_outputs(make_settings: Callable[..., Settings]) -> None:
    """各出力先に設定の値を配線する（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS
    from voice_paste.main import _wire_outputs

    # 準備
    adapters = MagicMock()
    settings = make_settings(
        {
            "keyboard": {"paste_key": "<ctrl>+<shift>+v"},
            "outputs": [
                {"id": "paste_and_send", "hotkey": "<ctrl>+<alt>+d", "enter_delay_sec": 0.2},
                {"id": "paste_only", "hotkey": "<ctrl>+<alt>+v"},
                {"id": "copy_only", "hotkey": "<ctrl>+<alt>+c"},
            ],
        }
    )
    deps = _make_output_deps(adapters, lambda: settings)

    # 実行
    wired = _wire_outputs(deps, OUTPUTS)
    _outputs_by_id(wired)["paste_and_send"].handler(_outcome(), None)

    # 検証
    assert [spec.id for spec in wired] == [spec.id for spec in OUTPUTS]
    adapters.send_paste.assert_called_once_with("<ctrl>+<shift>+v")
    adapters.sleep.assert_called_once_with(0.2)


def test_wire_outputs_when_settings_changed(
    default_settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    """配線の後に変えた設定が次の届け方に効く（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS
    from voice_paste.main import _wire_outputs

    # 準備
    adapters = MagicMock()
    get_settings = MagicMock(return_value=default_settings)
    deps = _make_output_deps(adapters, get_settings)
    wired = _wire_outputs(deps, OUTPUTS)

    # 配線の後に設定を差し替える
    get_settings.return_value = make_settings(
        {
            "keyboard": {"paste_key": "<ctrl>+<alt>+v"},
            "outputs": [
                {
                    "id": "paste_and_send",
                    "hotkey": "<ctrl>+<alt>+d",
                    "enter_delay_sec": 1.0,
                    "enter_modifiers": ["ctrl"],
                }
            ],
        }
    )

    # 実行
    _outputs_by_id(wired)["paste_and_send"].handler(_outcome(), None)

    # 検証
    adapters.send_paste.assert_called_once_with("<ctrl>+<alt>+v")
    adapters.sleep.assert_called_once_with(1.0)
    adapters.send_enter.assert_called_once_with(("ctrl",))


def test_wire_outputs_when_registered_output(default_settings: Settings) -> None:
    """登録しただけの出力先も、その inject が選んだもので配線される（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS, OutputSpec
    from voice_paste.main import _wire_outputs

    # 準備: OUTPUTS の後ろに、inject が copy だけを選ぶ試しの出力先を追加する
    adapters = MagicMock()
    deps = _make_output_deps(adapters, lambda: default_settings)
    trial = OutputSpec(
        id="trial",
        title="試し",
        handler=_trial_handler,  # type: ignore[arg-type] 注入する関数は _wire_outputs が部分適用する
        inject=lambda output_deps: {"copy": output_deps.copy},
    )

    # 実行
    wired = _wire_outputs(deps, (*OUTPUTS, trial))
    wired[-1].handler(_outcome(), None)

    # 検証
    assert wired[-1].id == "trial"
    adapters.copy_to_clipboard.assert_called_once_with("テスト")


# === _wire_preset_kinds ===


def test_wire_preset_kinds(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """各種類に設定の値を配線する（正常系）。"""
    from voice_paste.features.outputs import PRESET_KINDS
    from voice_paste.main import _wire_preset_kinds
    from voice_paste.shared.settings import BrowserPreset, EndpointPreset
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    adapters = _install_adapters(monkeypatch)
    settings = make_settings(
        {
            "outputs": [
                {"id": "paste_and_send", "hotkey": "<ctrl>+<alt>+d", "enter_delay_sec": 0.2}
            ],
            "preset_options": {
                "browser": {"open_delay_sec": 1.5},
                "endpoint": {"timeout_sec": 2.0},
            },
        }
    )
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )

    # 実行
    wired = _wire_preset_kinds(
        lambda: settings, open_window=adapters.open_app_window, send_paste=adapters.send_paste
    )
    by_kind = _kinds_by_name(wired)
    by_kind["browser"].handler(
        outcome, BrowserPreset(title="ChatGPT", url="https://chatgpt.com", send_enter=True)
    )
    browser_sleeps = list(adapters.sleep.mock_calls)
    by_kind["endpoint"].handler(
        outcome, EndpointPreset(title="受信先", url="http://127.0.0.1:9000/hook")
    )

    # 検証
    assert [spec.kind for spec in wired] == [spec.kind for spec in PRESET_KINDS]
    assert browser_sleeps == [call(1.5), call(0.2)]
    adapters.open_app_window.assert_called_once_with("https://chatgpt.com")
    adapters.post_json.assert_called_once()
    assert adapters.post_json.call_args.args[2] == 2.0


def test_wire_preset_kinds_when_settings_changed(
    monkeypatch: pytest.MonkeyPatch,
    default_settings: Settings,
    make_settings: Callable[..., Settings],
) -> None:
    """配線の後に変えたタイムアウトが次の送信に効く（正常系）。"""
    from voice_paste.main import _wire_preset_kinds
    from voice_paste.shared.settings import EndpointPreset
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    adapters = _install_adapters(monkeypatch)
    get_settings = MagicMock(return_value=default_settings)
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )
    wired = _wire_preset_kinds(
        get_settings, open_window=adapters.open_app_window, send_paste=adapters.send_paste
    )

    # 配線の後に設定を差し替える
    get_settings.return_value = make_settings(
        {"preset_options": {"endpoint": {"timeout_sec": 5.0}}}
    )

    # 実行
    _kinds_by_name(wired)["endpoint"].handler(
        outcome, EndpointPreset(title="受信先", url="http://127.0.0.1:9000/hook")
    )

    # 検証
    adapters.post_json.assert_called_once()
    assert adapters.post_json.call_args.args[2] == 5.0


# === build_hotkey_bindings ===


def _fixed_hotkey_settings(
    make_settings: Callable[..., Settings],
    *,
    confirm_enabled: bool = True,
    copy_enabled: bool = True,
) -> Settings:
    """ホットキーを OS の既定に頼らず固定した設定を返す（録音の開始は貼り付けて送信と同じキー）。"""
    return make_settings(
        {
            "hotkeys": {
                "start": "<ctrl>+<alt>+d",
                "pause": "<ctrl>+<alt>+z",
                "cancel": "<ctrl>+<alt>+q",
            },
            "outputs": [
                {"id": "paste_and_send", "hotkey": "<ctrl>+<alt>+d", "enabled": confirm_enabled},
                {"id": "paste_only", "hotkey": "<ctrl>+<alt>+v"},
                {"id": "copy_only", "hotkey": "<ctrl>+<alt>+c", "enabled": copy_enabled},
            ],
        }
    )


def test_build_hotkey_bindings_when_idle(make_settings: Callable[..., Settings]) -> None:
    """待機中の開始のホットキーは録音を始める（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = None
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(
        _fixed_hotkey_settings(make_settings), session_manager, start_local_session, MagicMock(), MagicMock()
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    start_local_session.assert_called_once_with("hotkey")
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_recording(make_settings: Callable[..., Settings]) -> None:
    """録音中の開始のホットキーは貼り付けて送信で確定する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    show_recording_window = MagicMock()
    bindings = build_hotkey_bindings(
        _fixed_hotkey_settings(make_settings), session_manager, start_local_session, show_recording_window, MagicMock()
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    session_manager.complete.assert_called_once_with(output_id="paste_and_send")
    start_local_session.assert_not_called()
    show_recording_window.assert_not_called()


def test_build_hotkey_bindings_when_recording_without_confirm_output(
    make_settings: Callable[..., Settings],
) -> None:
    """貼り付けて送信がオフなら、録音中の開始のホットキーは録音の画面を戻す指示を出す（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    settings = _fixed_hotkey_settings(make_settings, confirm_enabled=False)
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    show_recording_window = MagicMock()
    bindings = build_hotkey_bindings(
        settings, session_manager, start_local_session, show_recording_window, MagicMock()
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    show_recording_window.assert_called_once()
    start_local_session.assert_not_called()
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_preset(default_settings: Settings) -> None:
    """プリセットのホットキーはそのプリセットで確定する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import BrowserPreset

    # 準備
    preset = BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1")
    session_manager = MagicMock()
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(
        default_settings.model_copy(update={"presets": [preset]}),
        session_manager,
        start_local_session,
        MagicMock(),
        MagicMock(),
    )

    # 実行
    bindings["<ctrl>+<alt>+1"]()

    # 検証
    session_manager.complete.assert_called_once_with(preset=preset)


def test_build_hotkey_bindings_when_preset_not_bound(default_settings: Settings) -> None:
    """無効のプリセットとホットキーが空のプリセットは登録しない（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import BrowserPreset, EndpointPreset

    # 準備
    settings = default_settings.model_copy(
        update={
            "presets": [
                BrowserPreset(
                    title="ChatGPT",
                    url="https://chatgpt.com",
                    hotkey="<ctrl>+<alt>+7",
                    enabled=False,
                ),
                EndpointPreset(title="受信先", url="http://127.0.0.1:9000/hook"),
            ]
        }
    )

    # 実行
    bindings = build_hotkey_bindings(settings, MagicMock(), MagicMock(), MagicMock(), MagicMock())

    # 検証
    assert "<ctrl>+<alt>+7" not in bindings
    assert "" not in bindings



def test_build_hotkey_bindings_when_glossary_preset_hotkey(default_settings: Settings) -> None:
    """ショートカットの行のホットキーはそのプリセットへ切り替える（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import GlossaryPresetHotkeySettings

    # 準備（録音中に押す）
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    switch_glossary_preset = MagicMock()
    settings = default_settings.model_copy(
        update={
            "glossary_preset_hotkeys": [
                GlossaryPresetHotkeySettings(hotkey="<ctrl>+<alt>+s", preset="会議")
            ]
        }
    )
    bindings = build_hotkey_bindings(
        settings, session_manager, start_local_session, MagicMock(), switch_glossary_preset
    )

    # 実行
    bindings["<ctrl>+<alt>+s"]()

    # 検証
    switch_glossary_preset.assert_called_once_with("会議")
    session_manager.complete.assert_not_called()
    start_local_session.assert_not_called()

def test_build_hotkey_bindings_when_paused(make_settings: Callable[..., Settings]) -> None:
    """一時停止中の一時停止のホットキーは再開する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "paused")
    bindings = build_hotkey_bindings(_fixed_hotkey_settings(make_settings), session_manager, MagicMock(), MagicMock(), MagicMock())

    # 実行
    bindings["<ctrl>+<alt>+z"]()

    # 検証
    session_manager.resume.assert_called_once()
    session_manager.pause.assert_not_called()


def test_build_hotkey_bindings_when_output_disabled(make_settings: Callable[..., Settings]) -> None:
    """オフの出力先のホットキーは登録しない（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    settings = _fixed_hotkey_settings(make_settings, copy_enabled=False)

    # 実行
    bindings = build_hotkey_bindings(settings, MagicMock(), MagicMock(), MagicMock(), MagicMock())

    # 検証
    assert "<ctrl>+<alt>+c" not in bindings


def test_build_hotkey_bindings_when_transcribing(make_settings: Callable[..., Settings]) -> None:
    """文字起こし中の出力先のホットキーはその出力先へ差し替える（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "transcribing")
    bindings = build_hotkey_bindings(_fixed_hotkey_settings(make_settings), session_manager, MagicMock(), MagicMock(), MagicMock())

    # 実行
    bindings["<ctrl>+<alt>+c"]()

    # 検証
    session_manager.switch_output.assert_called_once_with("copy_only")
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_transcribing_start_hotkey(
    make_settings: Callable[..., Settings],
) -> None:
    """文字起こし中の開始のホットキーは、同じキーの出力先へ差し替えて録音を始めない（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "transcribing")
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(
        _fixed_hotkey_settings(make_settings), session_manager, start_local_session, MagicMock(), MagicMock()
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    session_manager.switch_output.assert_called_once_with("paste_and_send")
    start_local_session.assert_not_called()
    session_manager.complete.assert_not_called()


# === apply_settings ===


def _settings_paths(tmp_path: Path, local_settings_file: Path | None = None) -> AppPaths:
    """一時フォルダの置き場所を返す。既定値はリポジトリの config/defaults.yaml、checkout の上書きは local_settings_file。"""
    from voice_paste.shared.constants import resolve_app_paths

    return dataclasses.replace(
        resolve_app_paths(tmp_path),
        defaults_file=DEFAULTS_FILE,
        local_settings_file=local_settings_file,
    )


def test_apply_settings(
    tmp_path: Path,
    settings_model: type[Settings],
    default_settings: Settings,
    make_settings: Callable[..., Settings],
) -> None:
    """確かめてから書いて入れ替える（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    paths = _settings_paths(tmp_path)
    store = SettingsStore(default_settings)
    check_hotkeys = MagicMock()
    new_settings = make_settings(
        {
            "outputs": [
                {"id": "paste_and_send", "hotkey": "<ctrl>+<alt>+d"},
                {"id": "paste_only", "hotkey": "<ctrl>+<alt>+v"},
                {"id": "copy_only", "hotkey": "<ctrl>+<alt>+c", "enabled": False},
            ]
        }
    )

    # 実行
    restart_needed = apply_settings(
        new_settings,
        {},
        paths=paths,
        store=store,
        check_hotkeys=check_hotkeys,
        save_glossary=MagicMock(),
    )

    # 検証
    written = read_yaml_mapping(paths.settings_file)
    assert restart_needed is False
    check_hotkeys.assert_called_once()
    assert "<ctrl>+<alt>+c" not in set(check_hotkeys.call_args.args[0])
    assert {output["id"]: output["enabled"] for output in written["outputs"]}["copy_only"] is False
    assert load_settings(paths, settings_model) == new_settings
    assert store.get() == new_settings


def test_apply_settings_when_restart_item_changed(
    tmp_path: Path, default_settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    """再起動が要る項目の変更を返す（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore

    # 準備
    paths = _settings_paths(tmp_path)
    store = SettingsStore(default_settings)
    new_settings = make_settings({"transcription": {"local_whisper": {"model": "small"}}})

    # 実行
    restart_needed = apply_settings(
        new_settings,
        {},
        paths=paths,
        store=store,
        check_hotkeys=MagicMock(),
        save_glossary=MagicMock(),
    )

    # 検証
    assert restart_needed is True


def test_apply_settings_when_hotkey_unavailable(
    tmp_path: Path, default_settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    """受け付けられないホットキーなら何も書かない（異常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.errors import HotkeyError

    # 準備
    paths = _settings_paths(tmp_path)
    store = SettingsStore(default_settings)
    check_hotkeys = MagicMock(side_effect=HotkeyError("<ctrl>+<nokey> を読めない"))
    save_glossary = MagicMock()

    # 実行・検証
    with pytest.raises(HotkeyError):
        apply_settings(
            make_settings({"hotkeys": {"start": "<ctrl>+<nokey>"}}),
            {},
            paths=paths,
            store=store,
            check_hotkeys=check_hotkeys,
            save_glossary=save_glossary,
        )
    assert not paths.settings_file.exists()
    assert store.get() == default_settings
    save_glossary.assert_not_called()


def test_apply_settings_when_glossary_rows(
    tmp_path: Path,
    settings_model: type[Settings],
    default_settings: Settings,
    make_settings: Callable[..., Settings],
) -> None:
    """渡した用語集の CSV だけを書く（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の glossaries を持つ設定と、1 件目の場所だけを持つ glossary_rows）
    paths = _settings_paths(tmp_path)
    store = SettingsStore(default_settings)
    first_path = tmp_path / "glossaries" / "glossary_1.csv"
    second_path = tmp_path / "glossaries" / "glossary_2.csv"
    new_settings = make_settings(
        {
            "glossaries": [
                {"name": "yogo", "path": str(first_path)},
                {"name": "会議用", "path": str(second_path)},
            ]
        }
    )
    rows = [GlossaryEntry(wrong="あ", right="A", enabled=False)]
    save_glossary = MagicMock()

    # 実行
    apply_settings(
        new_settings,
        {first_path: rows},
        paths=paths,
        store=store,
        check_hotkeys=MagicMock(),
        save_glossary=save_glossary,
    )

    # 検証
    save_glossary.assert_called_once_with(first_path, rows)
    written = load_settings(paths, settings_model)
    assert [glossary.name for glossary in written.glossaries] == ["yogo", "会議用"]
    assert store.get() == new_settings


def test_apply_settings_when_glossary_write_fails(
    tmp_path: Path, default_settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    """用語集の CSV を書けなければ、設定を書かず入れ替えない（異常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.types import GlossaryEntry

    # 準備（save_glossary が OSError を送出する glossary_rows）
    paths = _settings_paths(tmp_path)
    store = SettingsStore(default_settings)
    glossary_path = tmp_path / "glossaries" / "glossary_1.csv"
    new_settings = make_settings({"glossaries": [{"name": "yogo", "path": str(glossary_path)}]})
    save_glossary = MagicMock(side_effect=OSError("disk full"))

    # 実行・検証
    with pytest.raises(OSError, match="disk full"):
        apply_settings(
            new_settings,
            {glossary_path: [GlossaryEntry(wrong="あ", right="A")]},
            paths=paths,
            store=store,
            check_hotkeys=MagicMock(),
            save_glossary=save_glossary,
        )
    assert not paths.settings_file.exists()
    assert store.get() == default_settings



# === switch_glossary_preset ===

GLOSSARY_PRESETS_FOR_SWITCH: list[dict[str, Any]] = [
    {"name": "既定", "glossaries": []},
    {"name": "会議", "glossaries": []},
]
"""切り替えのテストの用語集のプリセット（既定・会議）。"""


def test_switch_glossary_preset(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """補正に使用するプリセットを切り替えて保存する（正常系）。"""
    from voice_paste.main import switch_glossary_preset
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備
    paths = _settings_paths(tmp_path)
    store = SettingsStore(
        make_settings(
            {"glossary_presets": GLOSSARY_PRESETS_FOR_SWITCH, "active_glossary_preset": "既定"}
        )
    )

    # 実行
    result = switch_glossary_preset("会議", paths=paths, store=store)

    # 検証
    assert result is True
    assert read_yaml_mapping(paths.settings_file)["active_glossary_preset"] == "会議"
    assert store.latest().active_glossary_preset == "会議"


def test_switch_glossary_preset_when_already_active(
    tmp_path: Path, make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """すでにそのプリセットなら書き込まない（正常系）。"""
    import voice_paste.main as main_module
    from voice_paste.main import switch_glossary_preset
    from voice_paste.runtime.settings_store import SettingsStore

    # 準備
    save_settings = MagicMock()
    monkeypatch.setattr(main_module, "save_settings", save_settings)
    paths = _settings_paths(tmp_path)
    store = SettingsStore(
        make_settings(
            {"glossary_presets": GLOSSARY_PRESETS_FOR_SWITCH, "active_glossary_preset": "会議"}
        )
    )

    # 実行
    result = switch_glossary_preset("会議", paths=paths, store=store)

    # 検証
    assert result is True
    save_settings.assert_not_called()


def test_switch_glossary_preset_when_write_fails(
    tmp_path: Path,
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """書き込めなければ切り替えない（異常系）。"""
    import voice_paste.main as main_module
    from voice_paste.main import switch_glossary_preset
    from voice_paste.runtime.settings_store import SettingsStore

    # 準備
    monkeypatch.setattr(main_module, "save_settings", MagicMock(side_effect=OSError("disk full")))
    caplog.set_level(logging.ERROR)
    paths = _settings_paths(tmp_path)
    store = SettingsStore(
        make_settings(
            {"glossary_presets": GLOSSARY_PRESETS_FOR_SWITCH, "active_glossary_preset": "既定"}
        )
    )

    # 実行
    result = switch_glossary_preset("会議", paths=paths, store=store)

    # 検証
    assert result is False
    assert store.latest().active_glossary_preset == "既定"
    assert [record.levelno for record in caplog.records] == [logging.ERROR]


def test_switch_glossary_preset_after_apply_settings(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """設定画面の保存の直後に切り替えても、保存した値を失わない（正常系）。"""
    from voice_paste.main import apply_settings, switch_glossary_preset
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備: 音量を 30 にした設定を保存する
    paths = _settings_paths(tmp_path)
    store = SettingsStore(
        make_settings(
            {"glossary_presets": GLOSSARY_PRESETS_FOR_SWITCH, "active_glossary_preset": "既定"}
        )
    )
    apply_settings(
        make_settings(
            {
                "glossary_presets": GLOSSARY_PRESETS_FOR_SWITCH,
                "active_glossary_preset": "既定",
                "recording": {"volume_percent": 30},
            }
        ),
        {},
        paths=paths,
        store=store,
        check_hotkeys=MagicMock(),
        save_glossary=MagicMock(),
    )

    # 実行
    switch_glossary_preset("会議", paths=paths, store=store)

    # 検証
    written = read_yaml_mapping(paths.settings_file)
    assert store.latest().recording.volume_percent == 30
    assert written["recording"]["volume_percent"] == 30
    assert store.latest().active_glossary_preset == "会議"
    assert written["active_glossary_preset"] == "会議"

# === reset_applied_settings ===


def test_reset_applied_settings(
    tmp_path: Path, settings_model: type[Settings], default_settings: Settings
) -> None:
    """環境の値を空にし、既定値の設定に入れ替える（正常系）。"""
    from voice_paste.main import reset_applied_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings
    from voice_paste.shared.yaml_document import read_yaml_mapping

    # 準備（hotkeys.start と transcription.local_whisper.model を既定と違う値にした settings.yaml）
    paths = _settings_paths(tmp_path)
    paths.settings_file.parent.mkdir(parents=True, exist_ok=True)
    paths.settings_file.write_text(
        "hotkeys:\n  start: <ctrl>+<alt>+a\ntranscription:\n  local_whisper:\n    model: small\n",
        encoding="utf-8",
    )
    store = SettingsStore(load_settings(paths, settings_model))

    # 実行
    result = reset_applied_settings(paths=paths, store=store, model=settings_model)

    # 検証
    assert result == (default_settings, True)
    assert read_yaml_mapping(paths.settings_file) == {}
    assert store.get() == default_settings


def test_reset_applied_settings_when_local_override(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """checkout の上書きの値は残る（正常系）。"""
    from voice_paste.main import reset_applied_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings

    # 準備（settings.local.yaml に hotkeys.start = B、settings.yaml に hotkeys.start = A）
    local_settings_file = tmp_path / "checkout" / "settings.local.yaml"
    paths = _settings_paths(tmp_path, local_settings_file)
    local_text = "hotkeys:\n  start: <ctrl>+<alt>+b\n"
    local_settings_file.parent.mkdir(parents=True)
    local_settings_file.write_text(local_text, encoding="utf-8")
    paths.settings_file.parent.mkdir(parents=True, exist_ok=True)
    paths.settings_file.write_text("hotkeys:\n  start: <ctrl>+<alt>+a\n", encoding="utf-8")
    store = SettingsStore(load_settings(paths, settings_model))

    # 実行
    settings, _restart_needed = reset_applied_settings(
        paths=paths, store=store, model=settings_model
    )

    # 検証
    assert settings.hotkeys.start == "<ctrl>+<alt>+b"
    assert local_settings_file.read_text(encoding="utf-8") == local_text


# === purge_old_files ===

TODAY = date(2026, 10, 3)
"""purge_old_logs へ渡る今日として固定する日付。"""


def _install_purges(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    """main が使う purge_old_logs・purge_expired と今日の日付を差し替え、2 つの偽物を返す。"""
    import voice_paste.main as main_module

    purge_old_logs = MagicMock()
    purge_expired = MagicMock()
    monkeypatch.setattr(main_module, "purge_old_logs", purge_old_logs)
    monkeypatch.setattr(main_module, "purge_expired", purge_expired)
    monkeypatch.setattr(main_module, "local_today", lambda: TODAY)
    return purge_old_logs, purge_expired


def test_purge_old_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """ログと履歴の両方を削除する（正常系）。"""
    from voice_paste.main import purge_old_files
    from voice_paste.shared.constants import resolve_app_paths

    # 準備
    purge_old_logs, purge_expired = _install_purges(monkeypatch)
    paths = resolve_app_paths(tmp_path)
    settings = make_settings(
        {"history": {"enabled": True, "retention_days": 1}, "logging": {"retention_days": 7}}
    )
    active_session_ids = MagicMock(return_value={"session-1"})

    # 実行
    purge_old_files(settings, paths=paths, active_session_ids=active_session_ids)

    # 検証
    purge_old_logs.assert_called_once_with(paths.log_dir, 7, TODAY)
    purge_expired.assert_called_once()
    assert purge_expired.call_args.kwargs["retention_days"] == 1
    assert purge_expired.call_args.kwargs["paths"] == paths
    assert purge_expired.call_args.kwargs["active_session_ids"] is active_session_ids


def test_purge_old_files_when_history_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """履歴を残さない設定ならログだけ削除する（正常系）。"""
    from voice_paste.main import purge_old_files
    from voice_paste.shared.constants import resolve_app_paths

    # 準備
    purge_old_logs, purge_expired = _install_purges(monkeypatch)
    settings = make_settings({"history": {"enabled": False}})

    # 実行
    purge_old_files(
        settings, paths=resolve_app_paths(tmp_path), active_session_ids=MagicMock(return_value=set())
    )

    # 検証
    purge_old_logs.assert_called_once()
    purge_expired.assert_not_called()


# === build_handlers（Haas のエンジン） ===


def _build_haas_handlers(
    monkeypatch: pytest.MonkeyPatch,
    make_settings: Callable[..., Settings],
    tmp_path: Path,
    *,
    server_error: Exception | None = None,
    mismatch: tuple[str, ...] = (),
    unavailable: frozenset[Feature] = frozenset(),
) -> tuple[Handlers, MagicMock, MagicMock, MagicMock]:
    """エンジンが haas の設定で build_handlers を呼び、結果と HaasServer・WhisperWorkerClient・notify の偽物を返す。"""
    import voice_paste.main as main_module
    from voice_paste.shared.constants import resolve_app_paths

    server = MagicMock()
    server.return_value.ensure_started.side_effect = server_error
    server.return_value.ensure_started.return_value = mismatch
    worker = MagicMock()
    notify = MagicMock()
    monkeypatch.setattr(main_module, "HaasServer", server)
    monkeypatch.setattr(main_module, "WhisperWorkerClient", worker)
    monkeypatch.setattr(main_module, "ensure_local_whisper_installed", lambda: None)
    monkeypatch.setattr(main_module, "load_vad_session", MagicMock())
    handlers = main_module.build_handlers(
        make_settings({"transcription": {"engine": "haas"}}),
        resolve_app_paths(tmp_path),
        notify,
        MagicMock(),
        MagicMock(),
        adapters=MagicMock(),
        environ={},
        unavailable=unavailable,
    )
    return handlers, server, worker, notify


def test_build_handlers_when_haas(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """設定が haas でサーバーが応答する（正常系）。"""
    from voice_paste.features.transcription import EngineName

    # 実行
    handlers, server, worker, _notify = _build_haas_handlers(monkeypatch, make_settings, tmp_path)

    # 検証
    assert handlers.active_engine is EngineName.HAAS
    assert handlers.stop_engine == server.return_value.stop
    worker.assert_not_called()


def test_build_handlers_when_haas_settings_mismatch(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """動いている Haas のサーバーが設定と違う（正常系）。"""
    from voice_paste.features.transcription import EngineName

    # 実行
    handlers, _server, worker, notify = _build_haas_handlers(
        monkeypatch, make_settings, tmp_path, mismatch=("dtype", "device")
    )

    # 検証
    notify.assert_called_once_with("engine_settings_mismatch", "計算の精度・装置")
    assert handlers.active_engine is EngineName.HAAS
    worker.assert_not_called()


def test_build_handlers_when_haas_unavailable(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """サーバーへ接続できなければローカルの Whisper へ切り戻す（正常系）。"""
    from voice_paste.features.transcription import EngineName
    from voice_paste.shared.errors import EngineError

    # 実行
    handlers, _server, worker, notify = _build_haas_handlers(
        monkeypatch, make_settings, tmp_path, server_error=EngineError("接続できない")
    )

    # 検証
    notify.assert_called_once()
    assert "Haas のサーバーへ接続できないため、ローカルの Whisper で起こします。" in notify.call_args.args
    assert handlers.active_engine is EngineName.LOCAL_WHISPER
    worker.return_value.start.assert_called_once()
    assert handlers.web_api is not None
    assert handlers.web_api.reports_progress is True


def test_build_handlers_when_haas_not_supported_on_os(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """Haas を使えない OS では接続先を確かめずに切り戻す（正常系）。"""
    from voice_paste.features.transcription import EngineName
    from voice_paste.shared.os_kind import Feature

    # 実行
    handlers, server, worker, _notify = _build_haas_handlers(
        monkeypatch,
        make_settings,
        tmp_path,
        unavailable=frozenset({Feature.HAAS_ENGINE}),
    )

    # 検証
    server.return_value.ensure_started.assert_not_called()
    assert handlers.active_engine is EngineName.LOCAL_WHISPER
    worker.return_value.start.assert_called_once()
