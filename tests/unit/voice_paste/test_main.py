"""main.py（parse_args・main・start_local_session・build_hotkey_bindings・apply_settings・_wire_outputs・_wire_preset_kinds）の単体テスト。

main の配線（build_handlers）・API サーバー（ApiServerRunner）・上限の打ち切りのタイマー（RepeatingTimer）・
ホットキーの受付（HotkeyListener）・トレイ（Tray）・起動し直し（relaunch）は偽物に差し替え、
イベントループ（exec_loop）は、溜まったイベントを処理してすぐ戻る関数にする。
画面は offscreen の QApplication（conftest の qapp）を使い回す（main は QApplication が既にあればそれを使う）。
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, call

import pytest
from PySide6.QtCore import QTimer

from tests.unit.log_helpers import read_log_records
from tests.unit.voice_paste.ui.helpers import make_session
from voice_paste.shared.errors import StartupError

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from tests.unit.voice_paste.runtime.helpers import BackgroundAcquire
    from voice_paste.features.outputs import OutputSpec, PresetKindSpec
    from voice_paste.features.outputs.types import OutputDeps
    from voice_paste.shared.settings import Settings
    from voice_paste.shared.types import TranscriptionOutcome
    from voice_paste.ui.controller import UiDeps

ACQUIRE_WAIT_SEC = 5.0
"""別のスレッドで排他を取れるかが決まるのを待つ上限。"""

SHORT_ACQUIRE_TIMEOUT_SEC = 0.5
"""放されているはずの排他を取るときの待つ上限。"""

QUIT_LOOP_TIMEOUT_MS = 5000
"""終了を頼まれてもイベントループが抜けないときに、諦めて抜ける上限（ミリ秒）。"""

SIGNAL_NAMES = ("SIGINT", "SIGBREAK")
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
    tray_class: MagicMock
    relaunch: MagicMock
    ui_deps: list[UiDeps]
    """main が build_ui_deps で作った UiDeps（作られた順）。"""

    @property
    def hotkey(self) -> MagicMock:
        """main が作った HotkeyListener の偽物。"""
        return self.hotkey_class.return_value

    @property
    def tray(self) -> MagicMock:
        """main が作った Tray の偽物。"""
        return self.tray_class.return_value

    @property
    def runner(self) -> MagicMock:
        """main が作った ApiServerRunner の偽物。"""
        return self.runner_class.return_value


def install_wiring(
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
    *,
    api_started: bool = True,
    build_error: Exception | None = None,
) -> Wiring:
    """main が使う build_handlers・ApiServerRunner・RepeatingTimer・HotkeyListener・Tray・relaunch を偽物に差し替える。"""
    import voice_paste.main as main_module
    from voice_paste.main import Handlers
    from voice_paste.runtime.settings_store import SettingsStore

    calls: list[str] = []

    def _record(name: str) -> Callable[..., None]:
        """呼ばれたら name を calls に足す関数を返す。"""
        return lambda *_args, **_kwargs: calls.append(name)

    session_manager = MagicMock()
    session_manager.close.side_effect = _record("session_manager.close")

    def _build(
        settings: object,
        paths: object,
        notify: object,
        report_progress: object,
        notify_copied: object,
    ) -> Handlers:
        """配線済みの関数の束を、偽物で作る。"""
        return Handlers(
            session_manager=session_manager,
            session_api=MagicMock(),
            settings_store=SettingsStore(settings),
            start_local_session=MagicMock(),
            recorder_level=lambda: 0.0,
            stop_engine=_record("stop_engine"),
        )

    build_handlers = MagicMock(side_effect=build_error if build_error is not None else _build)

    runner_class = MagicMock()
    runner_class.return_value.start.return_value = api_started
    runner_class.return_value.stop.side_effect = _record("runner.stop")

    timer_class = MagicMock()
    timer_class.return_value.stop.side_effect = _record("timer.stop")

    hotkey_class = MagicMock()
    hotkey_class.return_value.stop.side_effect = _record("hotkey.stop")

    tray_class = MagicMock()
    tray_class.return_value.hide.side_effect = _record("tray.hide")

    relaunch = MagicMock(side_effect=_record("relaunch"))

    # build_ui_deps は本物のまま、作った UiDeps を控える（テストが request_restart などを呼べるように）
    ui_deps: list[UiDeps] = []
    real_build_ui_deps = main_module.build_ui_deps

    def _capture_ui_deps(*args: object, **kwargs: object) -> UiDeps:
        """本物の build_ui_deps で UiDeps を作り、控えて返す。"""
        deps = real_build_ui_deps(*args, **kwargs)
        ui_deps.append(deps)
        return deps

    monkeypatch.setattr(main_module, "build_handlers", build_handlers)
    monkeypatch.setattr(main_module, "ApiServerRunner", runner_class)
    monkeypatch.setattr(main_module, "RepeatingTimer", timer_class)
    monkeypatch.setattr(main_module, "HotkeyListener", hotkey_class)
    monkeypatch.setattr(main_module, "Tray", tray_class)
    monkeypatch.setattr(main_module, "relaunch", relaunch)
    monkeypatch.setattr(main_module, "build_ui_deps", _capture_ui_deps)
    return Wiring(
        calls=calls,
        build_handlers=build_handlers,
        runner_class=runner_class,
        timer_class=timer_class,
        hotkey_class=hotkey_class,
        tray_class=tray_class,
        relaunch=relaunch,
        ui_deps=ui_deps,
    )


def exit_after_events(app: QApplication) -> int:
    """溜まったイベント（知らせの Signal）を処理して、すぐ 0 を返す。main の exec_loop に渡す。"""
    app.processEvents()
    return 0


def timer_interval(timer_call: Any) -> float:
    """RepeatingTimer を作った呼び出しから、呼ぶ間隔（秒）を取り出す。"""
    if len(timer_call.args) > 1:
        return timer_call.args[1]
    return timer_call.kwargs["interval_sec"]


def record_lock_release(monkeypatch: pytest.MonkeyPatch, wiring: Wiring) -> None:
    """SingleInstanceLock.release が呼ばれたことを、止める操作の記録（wiring.calls）へ足す。本物の release も呼ぶ。"""
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
    lock: MagicMock, gave_up: list[bool]
) -> Callable[[QApplication], int]:
    """別のスレッドから終了を頼まれてから、本物のイベントループを回す exec_loop を作る。

    頼みが効かずにループが抜けないときのために、上限で諦めて抜け、gave_up に True を足す。
    """

    def _exec_loop(app: QApplication) -> int:
        """on_quit_requested に渡された関数を別のスレッドから呼び、ループを回す。"""
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
        SETTINGS_MODEL,
        main,
    )
    from voice_paste.runtime.single_instance import instance_name
    from voice_paste.shared.settings import load_settings

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    record_lock_release(monkeypatch, wiring)
    monkeypatch.delenv("VOICE_PASTE_ACCEPT_INJECTED_HOTKEYS", raising=False)

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exit_after_events)
    reacquired = background_acquire(instance_name(data_dir), SHORT_ACQUIRE_TIMEOUT_SEC)
    reacquired_decided = reacquired.wait(ACQUIRE_WAIT_SEC)

    # 検証
    assert exit_code == 0
    assert load_settings(data_dir / "settings.toml", SETTINGS_MODEL) == SETTINGS_MODEL()
    assert (data_dir / "api_token").exists()
    assert set(wiring.hotkey.start.call_args.args[0]) == DEFAULT_HOTKEYS
    assert wiring.hotkey_class.call_args.kwargs == {"accept_injected": False}
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


def test_main_when_accept_injected_hotkeys(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """環境変数が 1 なら、ソフトウェアで送ったキーもホットキーとして受ける受付を作る（正常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    monkeypatch.setenv("VOICE_PASTE_ACCEPT_INJECTED_HOTKEYS", "1")

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exit_after_events)

    # 検証
    assert exit_code == 0
    assert wiring.hotkey_class.call_args.kwargs == {"accept_injected": True}


def test_main_when_invalid_settings(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """設定が合わなければトレイで知らせて入口を立てない（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    (data_dir / "settings.toml").write_text(
        '[transcription.local_whisper]\nbeam_size = "x"\n', encoding="utf-8"
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exit_after_events)

    # 検証
    assert exit_code == 0
    wiring.tray.set_failed.assert_called_once()
    wiring.tray.show_failure.assert_called_once()
    assert wiring.tray.show_failure.call_args.args[0] == "settings_invalid"
    assert "transcription.local_whisper.beam_size" in wiring.tray.show_failure.call_args.args[1]
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
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exit_after_events)

    # 検証
    assert exit_code == 0
    wiring.tray.set_failed.assert_called_once()
    assert [c.args[0] for c in wiring.tray.show_failure.call_args_list] == ["engine_unavailable"]
    wiring.runner_class.assert_not_called()
    wiring.hotkey.start.assert_not_called()


def test_main_when_api_unavailable(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """待ち受けを始められなければトークンのファイルを書かずに知らせて続ける（正常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.settings import Settings

    # 準備
    wiring = install_wiring(monkeypatch, qapp, api_started=False)
    token_file = data_dir / "api_token"
    previous_content = '{"port": 1, "token": "previous-token"}'
    token_file.write_text(previous_content, encoding="utf-8")

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exit_after_events)

    # 検証
    assert exit_code == 0
    assert token_file.read_text(encoding="utf-8") == previous_content
    assert [c.args for c in wiring.tray.show_failure.call_args_list] == [
        ("api_unavailable", f"ポート {Settings().api.port} で待ち受けを始められません")
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
        """UiDeps.request_restart を呼んで、すぐ 0 を返す。"""
        wiring.ui_deps[0].request_restart()
        return 0

    argv = ["--data-dir", str(data_dir)]

    # 実行
    exit_code = main(argv, exec_loop=_request_restart)

    # 検証: 起動し直しは、API とエンジンを止めた後に 1 回だけ
    assert exit_code == 0
    wiring.relaunch.assert_called_once_with(argv)
    assert wiring.calls.index("relaunch") > wiring.calls.index("runner.stop")
    assert wiring.calls.index("relaunch") > wiring.calls.index("stop_engine")


def test_main_when_no_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """データの置き場所を渡さなければ既定の置き場所で起動する（正常系）。"""
    import voice_paste.shared.constants as constants_module
    from voice_paste.main import SETTINGS_MODEL, main
    from voice_paste.shared.settings import load_settings

    # 準備: platformdirs の置き場所を、一時フォルダの config・local へ向ける
    config_dir = tmp_path / "config"
    local_dir = tmp_path / "local"
    install_wiring(monkeypatch, qapp)
    monkeypatch.setattr(constants_module, "user_config_dir", lambda *_a, **_k: str(config_dir))
    monkeypatch.setattr(constants_module, "user_data_dir", lambda *_a, **_k: str(local_dir))

    # 実行
    exit_code = main([], exec_loop=exit_after_events)

    # 検証
    assert exit_code == 0
    assert load_settings(config_dir / "settings.toml", SETTINGS_MODEL) == SETTINGS_MODEL()
    assert (local_dir / "api_token").exists()
    assert list((local_dir / "log").glob("*.log"))


def test_main_when_previous_instance_not_released(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """前のプロセスが排他を放さなければトレイを出さずに終わる（異常系）。"""
    import voice_paste.main as main_module
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    monkeypatch.setattr(
        main_module,
        "acquire_single_instance",
        MagicMock(side_effect=StartupError("前の常駐サービスが終わらない")),
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exit_after_events)

    # 検証
    assert exit_code == 1
    assert len(read_log_records(data_dir / "log", "ERROR")) == 1
    wiring.tray_class.assert_not_called()
    wiring.build_handlers.assert_not_called()


def test_main_when_quit_requested(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """後から起動したプロセスに頼まれたら片付けて排他を放す（正常系）。"""
    import voice_paste.main as main_module
    from voice_paste.main import main

    # 準備: 排他は偽物（SingleInstanceLock の代わり）を返し、放したことを止める操作の記録へ足す
    wiring = install_wiring(monkeypatch, qapp)
    lock = MagicMock()
    lock.release.side_effect = lambda: wiring.calls.append("lock.release")
    monkeypatch.setattr(main_module, "acquire_single_instance", MagicMock(return_value=lock))
    gave_up: list[bool] = []
    about_to_quit_on_main_thread, stop_recording_quit = record_about_to_quit_threads(qapp)
    exec_loop = make_exec_loop_with_quit_request(lock, gave_up)

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
    `post_json` は 200 を返す。
    """
    import voice_paste.main as main_module
    from voice_paste.integrations.http.types import PostResult

    adapters = MagicMock()
    adapters.post_json.return_value = PostResult(status=200, retry_after_sec=None)
    monkeypatch.setattr(main_module, "copy_to_clipboard", adapters.copy_to_clipboard)
    monkeypatch.setattr(main_module, "send_paste", adapters.send_paste)
    monkeypatch.setattr(main_module, "send_enter", adapters.send_enter)
    monkeypatch.setattr(main_module, "open_app_window", adapters.open_app_window)
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


def test_wire_outputs(settings_model: type[Settings]) -> None:
    """各出力先に設定の値を配線する（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.main import _wire_outputs
    from voice_paste.shared.settings import KeyboardSettings

    # 準備
    adapters = MagicMock()
    settings = settings_model(
        keyboard=KeyboardSettings(paste_key="<ctrl>+<shift>+v"),
        outputs=[PasteAndSendSettings(enter_delay_sec=0.2), PasteOnlySettings(), CopyOnlySettings()],
    )
    deps = _make_output_deps(adapters, lambda: settings)

    # 実行
    wired = _wire_outputs(deps, OUTPUTS)
    _outputs_by_id(wired)["paste_and_send"].handler(_outcome(), None)

    # 検証
    assert [spec.id for spec in wired] == [spec.id for spec in OUTPUTS]
    adapters.send_paste.assert_called_once_with("<ctrl>+<shift>+v")
    adapters.sleep.assert_called_once_with(0.2)


def test_wire_outputs_when_settings_changed(settings_model: type[Settings]) -> None:
    """配線の後に変えた設定が次の届け方に効く（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.main import _wire_outputs
    from voice_paste.shared.settings import KeyboardSettings

    # 準備
    adapters = MagicMock()
    get_settings = MagicMock(return_value=settings_model())
    deps = _make_output_deps(adapters, get_settings)
    wired = _wire_outputs(deps, OUTPUTS)

    # 配線の後に設定を差し替える
    get_settings.return_value = settings_model(
        keyboard=KeyboardSettings(paste_key="<ctrl>+<alt>+v"),
        outputs=[PasteAndSendSettings(enter_delay_sec=1.0, enter_modifiers=["ctrl"])],
    )

    # 実行
    _outputs_by_id(wired)["paste_and_send"].handler(_outcome(), None)

    # 検証
    adapters.send_paste.assert_called_once_with("<ctrl>+<alt>+v")
    adapters.sleep.assert_called_once_with(1.0)
    adapters.send_enter.assert_called_once_with(("ctrl",))


def test_wire_outputs_when_registered_output(settings_model: type[Settings]) -> None:
    """登録しただけの出力先も、その inject が選んだもので配線される（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS, OutputSpec
    from voice_paste.main import _wire_outputs

    # 準備: OUTPUTS の後ろに、inject が copy だけを選ぶ試しの出力先を足す
    adapters = MagicMock()
    deps = _make_output_deps(adapters, lambda: settings_model())
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


def test_wire_preset_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    """各種類に設定の値を配線する（正常系）。"""
    from voice_paste.features.outputs import PRESET_KINDS
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.main import _wire_preset_kinds
    from voice_paste.shared.settings import (
        BrowserPreset,
        BrowserPresetOptions,
        EndpointPreset,
        EndpointPresetOptions,
        PresetOptions,
        Settings,
    )
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    adapters = _install_adapters(monkeypatch)
    settings = Settings(
        outputs=[PasteAndSendSettings(enter_delay_sec=0.2)],
        preset_options=PresetOptions(
            browser=BrowserPresetOptions(open_delay_sec=1.5),
            endpoint=EndpointPresetOptions(timeout_sec=2.0),
        ),
    )
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )

    # 実行
    wired = _wire_preset_kinds(lambda: settings)
    by_kind = _kinds_by_name(wired)
    by_kind["browser"].handler(
        outcome, BrowserPreset(title="ChatGPT", url="https://chatgpt.com", send_enter=True)
    )
    browser_sleeps = list(adapters.sleep.mock_calls)
    by_kind["endpoint"].handler(
        outcome, EndpointPreset(title="受け口", url="http://127.0.0.1:9000/hook")
    )

    # 検証
    assert [spec.kind for spec in wired] == [spec.kind for spec in PRESET_KINDS]
    assert browser_sleeps == [call(1.5), call(0.2)]
    adapters.open_app_window.assert_called_once_with("https://chatgpt.com")
    adapters.post_json.assert_called_once()
    assert adapters.post_json.call_args.args[2] == 2.0


def test_wire_preset_kinds_when_settings_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """配線の後に変えたタイムアウトが次の送りに効く（正常系）。"""
    from voice_paste.main import _wire_preset_kinds
    from voice_paste.shared.settings import (
        EndpointPreset,
        EndpointPresetOptions,
        PresetOptions,
        Settings,
    )
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    adapters = _install_adapters(monkeypatch)
    get_settings = MagicMock(return_value=Settings())
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )
    wired = _wire_preset_kinds(get_settings)

    # 配線の後に設定を差し替える
    get_settings.return_value = Settings(
        preset_options=PresetOptions(endpoint=EndpointPresetOptions(timeout_sec=5.0))
    )

    # 実行
    _kinds_by_name(wired)["endpoint"].handler(
        outcome, EndpointPreset(title="受け口", url="http://127.0.0.1:9000/hook")
    )

    # 検証
    adapters.post_json.assert_called_once()
    assert adapters.post_json.call_args.args[2] == 5.0


# === build_hotkey_bindings ===


def test_build_hotkey_bindings_when_idle(settings_model: type[Settings]) -> None:
    """待機中の開始のホットキーは録音を始める（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = None
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(
        settings_model(), session_manager, start_local_session, MagicMock()
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    start_local_session.assert_called_once_with("hotkey")
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_recording(settings_model: type[Settings]) -> None:
    """録音中の開始のホットキーは貼り付けて送信で確定する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    show_recording_window = MagicMock()
    bindings = build_hotkey_bindings(
        settings_model(), session_manager, start_local_session, show_recording_window
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    session_manager.complete.assert_called_once_with(output_id="paste_and_send")
    start_local_session.assert_not_called()
    show_recording_window.assert_not_called()


def test_build_hotkey_bindings_when_recording_without_confirm_output(
    settings_model: type[Settings],
) -> None:
    """貼り付けて送信がオフなら、録音中の開始のホットキーは録音の画面を戻す指示を出す（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.main import build_hotkey_bindings

    # 準備
    settings = settings_model(
        outputs=[PasteAndSendSettings(enabled=False), PasteOnlySettings(), CopyOnlySettings()]
    )
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    show_recording_window = MagicMock()
    bindings = build_hotkey_bindings(
        settings, session_manager, start_local_session, show_recording_window
    )

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    show_recording_window.assert_called_once()
    start_local_session.assert_not_called()
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_preset(settings_model: type[Settings]) -> None:
    """プリセットのホットキーはそのプリセットで確定する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import BrowserPreset

    # 準備
    preset = BrowserPreset(title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+1")
    session_manager = MagicMock()
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(
        settings_model(presets=[preset]), session_manager, start_local_session, MagicMock()
    )

    # 実行
    bindings["<ctrl>+<alt>+1"]()

    # 検証
    session_manager.complete.assert_called_once_with(preset=preset)


def test_build_hotkey_bindings_when_preset_not_bound(settings_model: type[Settings]) -> None:
    """無効のプリセットとホットキーが空のプリセットは登録しない（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import BrowserPreset, EndpointPreset

    # 準備
    settings = settings_model(
        presets=[
            BrowserPreset(
                title="ChatGPT", url="https://chatgpt.com", hotkey="<ctrl>+<alt>+7", enabled=False
            ),
            EndpointPreset(title="受け口", url="http://127.0.0.1:9000/hook"),
        ]
    )

    # 実行
    bindings = build_hotkey_bindings(settings, MagicMock(), MagicMock(), MagicMock())

    # 検証
    assert "<ctrl>+<alt>+7" not in bindings
    assert "" not in bindings


def test_build_hotkey_bindings_when_paused(settings_model: type[Settings]) -> None:
    """一時停止中の一時停止のホットキーは再開する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "paused")
    bindings = build_hotkey_bindings(settings_model(), session_manager, MagicMock(), MagicMock())

    # 実行
    bindings["<ctrl>+<alt>+z"]()

    # 検証
    session_manager.resume.assert_called_once()
    session_manager.pause.assert_not_called()


def test_build_hotkey_bindings_when_output_disabled(settings_model: type[Settings]) -> None:
    """オフの出力先のホットキーは登録しない（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.main import build_hotkey_bindings

    # 準備
    settings = settings_model(
        outputs=[PasteAndSendSettings(), PasteOnlySettings(), CopyOnlySettings(enabled=False)]
    )

    # 実行
    bindings = build_hotkey_bindings(settings, MagicMock(), MagicMock(), MagicMock())

    # 検証
    assert "<ctrl>+<alt>+c" not in bindings


# === apply_settings ===


def test_apply_settings(tmp_path: Path, settings_model: type[Settings]) -> None:
    """確かめてから書いて入れ替える（正常系）。"""
    from voice_paste.features.outputs.copy_only.settings import CopyOnlySettings
    from voice_paste.features.outputs.paste_and_send.settings import PasteAndSendSettings
    from voice_paste.features.outputs.paste_only.settings import PasteOnlySettings
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import load_settings

    # 準備
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file, settings_model))
    check_hotkeys = MagicMock()
    new_settings = settings_model(
        outputs=[PasteAndSendSettings(), PasteOnlySettings(), CopyOnlySettings(enabled=False)]
    )

    # 実行
    restart_needed = apply_settings(
        new_settings,
        {},
        settings_file=settings_file,
        store=store,
        check_hotkeys=check_hotkeys,
        save_glossary=MagicMock(),
    )

    # 検証
    assert restart_needed is False
    check_hotkeys.assert_called_once()
    assert "<ctrl>+<alt>+c" not in set(check_hotkeys.call_args.args[0])
    assert load_settings(settings_file, settings_model) == new_settings
    assert store.get() == new_settings


def test_apply_settings_when_restart_item_changed(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """再起動が要る項目の変更を返す（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import (
        LocalWhisperSettings,
        TranscriptionSettings,
        load_settings,
    )

    # 準備
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file, settings_model))
    new_settings = settings_model(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small"))
    )

    # 実行
    restart_needed = apply_settings(
        new_settings,
        {},
        settings_file=settings_file,
        store=store,
        check_hotkeys=MagicMock(),
        save_glossary=MagicMock(),
    )

    # 検証
    assert restart_needed is True


def test_apply_settings_when_hotkey_unavailable(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """受け付けられないホットキーなら何も書かない（異常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.errors import HotkeyError
    from voice_paste.shared.settings import HotkeySettings, load_settings

    # 準備
    settings_file = tmp_path / "settings.toml"
    previous_settings = load_settings(settings_file, settings_model)
    settings_before = settings_file.read_bytes()
    store = SettingsStore(previous_settings)
    check_hotkeys = MagicMock(side_effect=HotkeyError("<ctrl>+<nokey> を読めない"))
    save_glossary = MagicMock()

    # 実行・検証
    with pytest.raises(HotkeyError):
        apply_settings(
            settings_model(hotkeys=HotkeySettings(start="<ctrl>+<nokey>")),
            {},
            settings_file=settings_file,
            store=store,
            check_hotkeys=check_hotkeys,
            save_glossary=save_glossary,
        )
    assert settings_file.read_bytes() == settings_before
    assert store.get() == previous_settings
    save_glossary.assert_not_called()


def test_apply_settings_when_glossary_rows(tmp_path: Path, settings_model: type[Settings]) -> None:
    """渡した用語集の CSV だけを書く（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import GlossarySettings, load_settings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（2 件の glossaries を持つ設定と、1 件目の場所だけを持つ glossary_rows）
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file, settings_model))
    first_path = tmp_path / "glossaries" / "glossary_1.csv"
    second_path = tmp_path / "glossaries" / "glossary_2.csv"
    new_settings = settings_model(
        glossaries=[
            GlossarySettings(name="yogo", path=first_path),
            GlossarySettings(name="会議用", path=second_path),
        ]
    )
    rows = [GlossaryEntry(wrong="あ", right="A", enabled=False)]
    save_glossary = MagicMock()

    # 実行
    apply_settings(
        new_settings,
        {first_path: rows},
        settings_file=settings_file,
        store=store,
        check_hotkeys=MagicMock(),
        save_glossary=save_glossary,
    )

    # 検証
    save_glossary.assert_called_once_with(first_path, rows)
    written = load_settings(settings_file, settings_model)
    assert [glossary.name for glossary in written.glossaries] == ["yogo", "会議用"]
    assert store.get() == new_settings


def test_apply_settings_when_glossary_write_fails(
    tmp_path: Path, settings_model: type[Settings]
) -> None:
    """用語集の CSV を書けなければ、設定を書かず入れ替えない（異常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import GlossarySettings, load_settings
    from voice_paste.shared.types import GlossaryEntry

    # 準備（save_glossary が OSError を送出する glossary_rows）
    settings_file = tmp_path / "settings.toml"
    previous_settings = load_settings(settings_file, settings_model)
    settings_before = settings_file.read_bytes()
    store = SettingsStore(previous_settings)
    glossary_path = tmp_path / "glossaries" / "glossary_1.csv"
    new_settings = settings_model(glossaries=[GlossarySettings(name="yogo", path=glossary_path)])
    save_glossary = MagicMock(side_effect=OSError("disk full"))

    # 実行・検証
    with pytest.raises(OSError, match="disk full"):
        apply_settings(
            new_settings,
            {glossary_path: [GlossaryEntry(wrong="あ", right="A")]},
            settings_file=settings_file,
            store=store,
            check_hotkeys=MagicMock(),
            save_glossary=save_glossary,
        )
    assert settings_file.read_bytes() == settings_before
    assert store.get() == previous_settings


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


def test_purge_old_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ログと履歴の両方を消す（正常系）。"""
    from voice_paste.main import purge_old_files
    from voice_paste.shared.constants import resolve_app_paths
    from voice_paste.shared.settings import HistorySettings, LoggingSettings, Settings

    # 準備
    purge_old_logs, purge_expired = _install_purges(monkeypatch)
    paths = resolve_app_paths(tmp_path)
    settings = Settings(
        history=HistorySettings(enabled=True, retention_days=1),
        logging=LoggingSettings(retention_days=7),
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """履歴を残さない設定ならログだけ消す（正常系）。"""
    from voice_paste.main import purge_old_files
    from voice_paste.shared.constants import resolve_app_paths
    from voice_paste.shared.settings import HistorySettings, Settings

    # 準備
    purge_old_logs, purge_expired = _install_purges(monkeypatch)
    settings = Settings(history=HistorySettings(enabled=False))

    # 実行
    purge_old_files(
        settings, paths=resolve_app_paths(tmp_path), active_session_ids=MagicMock(return_value=set())
    )

    # 検証
    purge_old_logs.assert_called_once()
    purge_expired.assert_not_called()
