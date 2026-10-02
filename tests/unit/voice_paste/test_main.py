"""main.py（parse_args・並走の間の main・log_notify）の単体テスト。

main の配線（build_handlers）・API サーバー（ApiServerRunner）・上限の打ち切りのタイマー（RepeatingTimer）は
偽物に差し替え、終了の合図の待ち（wait_for_shutdown）はすぐ戻る関数にする。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest

from tests.unit.log_helpers import read_log_records
from voice_paste.shared.errors import StartupError

if TYPE_CHECKING:
    from voice_paste.features.outputs import OutputSpec


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
    log_notify: MagicMock
    wait_for_shutdown: Callable[[], None]

    def notified_events(self) -> list[str]:
        """log_notify に渡された知らせの種類を、渡された順に返す。"""
        return [call.args[0] for call in self.log_notify.call_args_list]


def install_wiring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_started: bool = True,
    build_error: Exception | None = None,
) -> Wiring:
    """main が使う build_handlers・ApiServerRunner・RepeatingTimer・log_notify を偽物に差し替える。"""
    import voice_paste.main as main_module
    from voice_paste.main import Handlers

    calls: list[str] = []

    def _record(name: str) -> Callable[..., None]:
        """呼ばれたら name を calls に足す関数を返す。"""
        return lambda *_args, **_kwargs: calls.append(name)

    session_manager = MagicMock()
    session_manager.close.side_effect = _record("session_manager.close")

    def _build(settings: object, paths: object, notify: object) -> Handlers:
        """配線済みの関数の束を、偽物で作る。"""
        return Handlers(
            session_manager=session_manager,
            session_api=MagicMock(),
            settings=settings,
            stop_engine=_record("stop_engine"),
        )

    build_handlers = MagicMock(side_effect=build_error if build_error is not None else _build)

    runner_class = MagicMock()
    runner_class.return_value.start.return_value = api_started
    runner_class.return_value.stop.side_effect = _record("runner.stop")

    timer_class = MagicMock()
    timer_class.return_value.stop.side_effect = _record("timer.stop")

    log_notify = MagicMock()

    monkeypatch.setattr(main_module, "build_handlers", build_handlers)
    monkeypatch.setattr(main_module, "ApiServerRunner", runner_class)
    monkeypatch.setattr(main_module, "RepeatingTimer", timer_class)
    monkeypatch.setattr(main_module, "log_notify", log_notify)
    return Wiring(
        calls=calls,
        build_handlers=build_handlers,
        runner_class=runner_class,
        timer_class=timer_class,
        log_notify=log_notify,
        wait_for_shutdown=_record("wait_for_shutdown"),
    )


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
    """データの置き場所が無ければ終わる（異常系）。"""
    from voice_paste.main import parse_args

    # 実行・検証
    with pytest.raises(SystemExit) as exc_info:
        parse_args([])
    assert exc_info.value.code == 2


# === main ===


def test_main(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """設定を読んで API を立て、終了の合図で片付けて 0 を返す（正常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.settings import Settings, load_settings

    # 準備
    wiring = install_wiring(monkeypatch)

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], wait_for_shutdown=wiring.wait_for_shutdown)

    # 検証
    assert exit_code == 0
    assert load_settings(data_dir / "settings.toml") == Settings()
    assert "設定を読んだ" in str(read_log_records(data_dir / "log", "INFO"))
    assert (data_dir / "api_token").exists()
    assert wiring.calls == [
        "wait_for_shutdown",
        "timer.stop",
        "runner.stop",
        "session_manager.close",
        "stop_engine",
    ]


def test_main_when_migrate_env(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env を移してから読む（正常系）。"""
    from voice_paste.main import main
    from voice_paste.shared.settings import load_settings

    # 準備
    wiring = install_wiring(monkeypatch)
    env_path = tmp_path / ".env"
    env_content = "WHISPER_MODEL=small\n"
    env_path.write_text(env_content, encoding="utf-8")

    # 実行
    exit_code = main(
        ["--data-dir", str(data_dir), "--migrate-env", str(env_path)],
        wait_for_shutdown=wiring.wait_for_shutdown,
    )

    # 検証
    assert exit_code == 0
    assert load_settings(data_dir / "settings.toml").transcription.local_whisper.model == "small"
    assert env_path.read_text(encoding="utf-8") == env_content
    assert not (tmp_path / ".env.migrated").exists()


def test_main_when_settings_exists_and_migrate_env(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """設定ファイルがあれば移さない（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch)
    settings_file = data_dir / "settings.toml"
    settings_file.write_text('[hotkeys]\nstart = "<ctrl>+<alt>+s"\n', encoding="utf-8")
    settings_before = settings_file.read_bytes()
    env_path = tmp_path / ".env"
    env_path.write_text("WHISPER_MODEL=small\n", encoding="utf-8")

    # 実行
    exit_code = main(
        ["--data-dir", str(data_dir), "--migrate-env", str(env_path)],
        wait_for_shutdown=wiring.wait_for_shutdown,
    )

    # 検証
    assert exit_code == 1
    assert settings_file.read_bytes() == settings_before
    assert len(read_log_records(data_dir / "log", "ERROR")) == 1
    wiring.build_handlers.assert_not_called()


def test_main_when_invalid_settings(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """設定が合わなければ 1 を返す（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch)
    (data_dir / "settings.toml").write_text(
        '[transcription.local_whisper]\nbeam_size = "x"\n', encoding="utf-8"
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], wait_for_shutdown=wiring.wait_for_shutdown)

    # 検証
    assert exit_code == 1
    assert "transcription.local_whisper.beam_size" in str(
        read_log_records(data_dir / "log", "ERROR")
    )
    wiring.build_handlers.assert_not_called()


def test_main_when_startup_error(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """エンジンを準備できなければ 1 を返す（異常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(
        monkeypatch, build_error=StartupError("文字起こしのエンジンを準備できない")
    )

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], wait_for_shutdown=wiring.wait_for_shutdown)

    # 検証
    assert exit_code == 1
    assert len(read_log_records(data_dir / "log", "ERROR")) == 1
    wiring.runner_class.assert_not_called()


def test_main_when_api_unavailable(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """待ち受けを始められなければトークンのファイルを書かずに知らせて 1 を返す（正常系）。"""
    from voice_paste.main import main

    # 準備
    wiring = install_wiring(monkeypatch, api_started=False)
    token_file = data_dir / "api_token"
    previous_content = '{"port": 1, "token": "previous-token"}'
    token_file.write_text(previous_content, encoding="utf-8")

    # 実行
    exit_code = main(["--data-dir", str(data_dir)], wait_for_shutdown=wiring.wait_for_shutdown)

    # 検証
    assert exit_code == 1
    assert token_file.read_text(encoding="utf-8") == previous_content
    assert "api_unavailable" in wiring.notified_events()
    assert wiring.calls.count("stop_engine") == 1
    assert "wait_for_shutdown" not in wiring.calls


# === log_notify ===


def test_log_notify_when_failure(caplog: pytest.LogCaptureFixture) -> None:
    """失敗の知らせは WARNING（正常系）。"""
    from voice_paste.main import log_notify

    # 準備
    caplog.set_level(logging.INFO)

    # 実行
    log_notify("api_unavailable", "47823")

    # 検証
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "api_unavailable" in warnings[0].getMessage()
    assert "47823" in warnings[0].getMessage()


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
