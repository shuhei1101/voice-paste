"""main.py（parse_args・main・start_local_session・build_hotkey_bindings・apply_settings・_wire_outputs）の単体テスト。

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
    from voice_paste.features.outputs import OutputSpec
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
    "<ctrl>+<alt>+1",
    "<ctrl>+<alt>+2",
    "<ctrl>+<alt>+3",
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

    def _build(settings: object, paths: object, notify: object, report_progress: object) -> Handlers:
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


def spy_quit_thread(monkeypatch: pytest.MonkeyPatch, app: QApplication) -> list[bool]:
    """Python から呼ばれた QApplication.quit が、メインスレッドで呼ばれたか（呼ばれた順）を控える。本物の quit も呼ぶ。"""
    on_main_thread: list[bool] = []
    original_quit = app.quit

    def _quit() -> None:
        """呼んだスレッドを控えてから本物の quit を呼ぶ。"""
        on_main_thread.append(threading.current_thread() is threading.main_thread())
        original_quit()

    monkeypatch.setattr(app, "quit", _quit)
    return on_main_thread


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
    from voice_paste.main import parse_args

    # 実行
    args = parse_args(["--data-dir", "C:/tmp/vp"])

    # 検証
    assert args.data_dir == Path("C:/tmp/vp")
    assert args.migrate_env is None


def test_parse_args_when_migrate_env() -> None:
    """移す .env も読む（正常系）。"""
    from voice_paste.main import parse_args

    # 実行
    args = parse_args(["--data-dir", "C:/tmp/vp", "--migrate-env", "C:/repo/.env"])

    # 検証
    assert args.migrate_env == Path("C:/repo/.env")


def test_parse_args_when_no_data_dir() -> None:
    """データの置き場所が無ければ既定の置き場所にする（正常系）。"""
    from voice_paste.main import parse_args

    # 実行
    args = parse_args([])

    # 検証
    assert args.data_dir is None
    assert args.migrate_env is None


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
    from voice_paste.main import PURGE_INTERVAL_SEC, SESSION_LIMIT_CHECK_INTERVAL_SEC, main
    from voice_paste.runtime.single_instance import instance_name
    from voice_paste.shared.settings import Settings, load_settings

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
    assert load_settings(data_dir / "settings.toml") == Settings()
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


def test_main_when_migrate_env(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """.env を移してから読む（正常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.settings import load_settings

    # 準備
    install_wiring(monkeypatch, qapp)
    env_path = tmp_path / ".env"
    env_content = "WHISPER_MODEL=small\n"
    env_path.write_text(env_content, encoding="utf-8")

    # 実行
    exit_code = main(
        ["--data-dir", str(data_dir), "--migrate-env", str(env_path)],
        exec_loop=exit_after_events,
    )

    # 検証
    assert exit_code == 0
    assert load_settings(data_dir / "settings.toml").transcription.local_whisper.model == "small"
    assert env_path.read_text(encoding="utf-8") == env_content
    assert not (tmp_path / ".env.migrated").exists()


def test_main_when_settings_exists_and_migrate_env(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    """設定ファイルがあれば移さない（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, qapp)
    settings_file = data_dir / "settings.toml"
    settings_file.write_text('[hotkeys]\nstart = "<ctrl>+<alt>+s"\n', encoding="utf-8")
    settings_before = settings_file.read_bytes()
    env_path = tmp_path / ".env"
    env_path.write_text("WHISPER_MODEL=small\n", encoding="utf-8")

    # 実行
    exit_code = main(
        ["--data-dir", str(data_dir), "--migrate-env", str(env_path)],
        exec_loop=exit_after_events,
    )

    # 検証
    assert exit_code == 1
    assert settings_file.read_bytes() == settings_before
    assert len(read_log_records(data_dir / "log", "ERROR")) == 1
    wiring.build_handlers.assert_not_called()


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
    from voice_paste.main import main
    from voice_paste.shared.settings import Settings, load_settings

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
    assert load_settings(config_dir / "settings.toml") == Settings()
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
    quit_on_main_thread = spy_quit_thread(monkeypatch, qapp)
    exec_loop = make_exec_loop_with_quit_request(lock, gave_up)

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], exec_loop=exec_loop)

    # 検証: 頼みでイベントループが抜け（上限で諦めていない）、止めた後に排他を 1 回だけ放し、起動し直さない
    assert exit_code == 0
    assert gave_up == []
    assert False not in quit_on_main_thread
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
    """main が出力先へ渡す外部連携と time.sleep を偽物に差し替え、呼ばれた順を持つ親の Mock を返す。

    親の `copy_to_clipboard`・`send_paste`・`send_enter`・`open_app_window`・`sleep` がそれぞれの偽物。
    """
    import voice_paste.main as main_module

    adapters = MagicMock()
    monkeypatch.setattr(main_module, "copy_to_clipboard", adapters.copy_to_clipboard)
    monkeypatch.setattr(main_module, "send_paste", adapters.send_paste)
    monkeypatch.setattr(main_module, "send_enter", adapters.send_enter)
    monkeypatch.setattr(main_module, "open_app_window", adapters.open_app_window)
    monkeypatch.setattr("time.sleep", adapters.sleep)
    return adapters


def _outputs_by_id(wired: tuple[OutputSpec, ...]) -> dict[str, OutputSpec]:
    """配線した出力先の一覧を、出力先の ID で引ける dict にする。"""
    return {spec.id: spec for spec in wired}


def test_wire_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """各出力先に設定の値を配線する（正常系）。"""
    from voice_paste.features.outputs import OUTPUTS
    from voice_paste.main import _wire_outputs
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        KeyboardSettings,
        PasteAndSendSettings,
        PasteOnlySettings,
        Settings,
    )
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    adapters = _install_adapters(monkeypatch)
    settings = Settings(
        keyboard=KeyboardSettings(paste_key="<ctrl>+<shift>+v"),
        outputs=[
            PasteAndSendSettings(enter_delay_sec=0.2),
            PasteOnlySettings(),
            CopyOnlySettings(),
            AiChatSettings(open_delay_sec=1.5),
        ],
    )
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )

    # 実行
    wired = _wire_outputs(lambda: settings)
    by_id = _outputs_by_id(wired)
    by_id["paste_and_send"].handler(outcome, None)
    paste_and_send_sleeps = list(adapters.sleep.mock_calls)
    adapters.sleep.reset_mock()
    by_id["ai_chat"].handler(outcome, "https://chatgpt.com")
    ai_chat_sleeps = list(adapters.sleep.mock_calls)

    # 検証
    assert [spec.id for spec in wired] == [spec.id for spec in OUTPUTS]
    adapters.send_paste.assert_called_with("<ctrl>+<shift>+v")
    assert paste_and_send_sleeps == [call(0.2)]
    adapters.open_app_window.assert_called_once_with("https://chatgpt.com")
    assert ai_chat_sleeps == [call(1.5), call(0.2)]


def test_wire_outputs_when_settings_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """配線の後に変えた設定が次の届け方に効く（正常系）。"""
    from voice_paste.main import _wire_outputs
    from voice_paste.shared.settings import (
        KeyboardSettings,
        PasteAndSendSettings,
        Settings,
    )
    from voice_paste.shared.types import TranscriptionOutcome

    # 準備
    adapters = _install_adapters(monkeypatch)
    get_settings = MagicMock(return_value=Settings())
    outcome = TranscriptionOutcome(
        session_id="session-1", result="transcribed", text="テスト", error=None
    )
    wired = _wire_outputs(get_settings)

    # 配線の後に設定を差し替える
    get_settings.return_value = Settings(
        keyboard=KeyboardSettings(paste_key="<ctrl>+<alt>+v"),
        outputs=[PasteAndSendSettings(enter_delay_sec=1.0)],
    )

    # 実行
    _outputs_by_id(wired)["paste_and_send"].handler(outcome, None)

    # 検証
    adapters.send_paste.assert_called_once_with("<ctrl>+<alt>+v")
    adapters.sleep.assert_called_once_with(1.0)


# === build_hotkey_bindings ===


def test_build_hotkey_bindings_when_idle() -> None:
    """待機中の開始のホットキーは録音を始める（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import Settings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = None
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(Settings(), session_manager, start_local_session)

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    start_local_session.assert_called_once_with("hotkey")
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_recording() -> None:
    """録音中の開始のホットキーは貼り付けて送信で確定する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import Settings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(Settings(), session_manager, start_local_session)

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    session_manager.complete.assert_called_once_with(output_id="paste_and_send")
    start_local_session.assert_not_called()


def test_build_hotkey_bindings_when_recording_without_confirm_output() -> None:
    """貼り付けて送信がオフなら、録音中の開始のホットキーは何もしない（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
        Settings,
    )

    # 準備
    settings = Settings(
        outputs=[
            PasteAndSendSettings(enabled=False),
            PasteOnlySettings(),
            CopyOnlySettings(),
            AiChatSettings(),
        ]
    )
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "recording")
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(settings, session_manager, start_local_session)

    # 実行
    bindings["<ctrl>+<alt>+d"]()

    # 検証
    start_local_session.assert_not_called()
    session_manager.complete.assert_not_called()


def test_build_hotkey_bindings_when_ai_chat_target() -> None:
    """送り先のホットキーはその URL で確定する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import Settings

    # 準備
    session_manager = MagicMock()
    start_local_session = MagicMock()
    bindings = build_hotkey_bindings(Settings(), session_manager, start_local_session)

    # 実行
    bindings["<ctrl>+<alt>+1"]()

    # 検証
    session_manager.complete.assert_called_once_with(
        output_id="ai_chat", output_target="https://chatgpt.com"
    )


def test_build_hotkey_bindings_when_paused() -> None:
    """一時停止中の一時停止のホットキーは再開する（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import Settings

    # 準備
    session_manager = MagicMock()
    session_manager.current.return_value = make_session("hotkey", "paused")
    bindings = build_hotkey_bindings(Settings(), session_manager, MagicMock())

    # 実行
    bindings["<ctrl>+<alt>+z"]()

    # 検証
    session_manager.resume.assert_called_once()
    session_manager.pause.assert_not_called()


def test_build_hotkey_bindings_when_output_disabled() -> None:
    """オフの出力先のホットキーは登録しない（正常系）。"""
    from voice_paste.main import build_hotkey_bindings
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
        Settings,
    )

    # 準備
    settings = Settings(
        outputs=[
            PasteAndSendSettings(),
            PasteOnlySettings(),
            CopyOnlySettings(enabled=False),
            AiChatSettings(),
        ]
    )

    # 実行
    bindings = build_hotkey_bindings(settings, MagicMock(), MagicMock())

    # 検証
    assert "<ctrl>+<alt>+c" not in bindings


# === apply_settings ===


def test_apply_settings(tmp_path: Path) -> None:
    """確かめてから書いて入れ替える（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import (
        AiChatSettings,
        CopyOnlySettings,
        PasteAndSendSettings,
        PasteOnlySettings,
        Settings,
        load_settings,
    )

    # 準備
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file))
    check_hotkeys = MagicMock()
    new_settings = Settings(
        outputs=[
            PasteAndSendSettings(),
            PasteOnlySettings(),
            CopyOnlySettings(enabled=False),
            AiChatSettings(),
        ]
    )

    # 実行
    restart_needed = apply_settings(
        new_settings, settings_file=settings_file, store=store, check_hotkeys=check_hotkeys
    )

    # 検証
    assert restart_needed is False
    check_hotkeys.assert_called_once()
    assert "<ctrl>+<alt>+c" not in set(check_hotkeys.call_args.args[0])
    assert load_settings(settings_file) == new_settings
    assert store.get() == new_settings


def test_apply_settings_when_restart_item_changed(tmp_path: Path) -> None:
    """再起動が要る項目の変更を返す（正常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.settings import (
        LocalWhisperSettings,
        Settings,
        TranscriptionSettings,
        load_settings,
    )

    # 準備
    settings_file = tmp_path / "settings.toml"
    store = SettingsStore(load_settings(settings_file))
    new_settings = Settings(
        transcription=TranscriptionSettings(local_whisper=LocalWhisperSettings(model="small"))
    )

    # 実行
    restart_needed = apply_settings(
        new_settings, settings_file=settings_file, store=store, check_hotkeys=MagicMock()
    )

    # 検証
    assert restart_needed is True


def test_apply_settings_when_hotkey_unavailable(tmp_path: Path) -> None:
    """受け付けられないホットキーなら何も書かない（異常系）。"""
    from voice_paste.main import apply_settings
    from voice_paste.runtime.settings_store import SettingsStore
    from voice_paste.shared.errors import HotkeyError
    from voice_paste.shared.settings import HotkeySettings, Settings, load_settings

    # 準備
    settings_file = tmp_path / "settings.toml"
    previous_settings = load_settings(settings_file)
    settings_before = settings_file.read_bytes()
    store = SettingsStore(previous_settings)
    check_hotkeys = MagicMock(side_effect=HotkeyError("<ctrl>+<nokey> を読めない"))

    # 実行・検証
    with pytest.raises(HotkeyError):
        apply_settings(
            Settings(hotkeys=HotkeySettings(start="<ctrl>+<nokey>")),
            settings_file=settings_file,
            store=store,
            check_hotkeys=check_hotkeys,
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
