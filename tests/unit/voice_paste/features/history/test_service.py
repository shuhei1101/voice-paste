"""features/history/service.py（save_recording・store_web_audio・append_text・discard_temporary・purge_expired）の単体テスト。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from voice_paste.shared.constants import AppPaths, resolve_app_paths

SAMPLE_RATE = 16000
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
WEB_NOW = datetime(2026, 10, 23, 14, 5, tzinfo=UTC)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """一時フォルダを置き場所にした AppPaths を返す。"""
    return resolve_app_paths(tmp_path)


def _now() -> datetime:
    """固定の今の時刻（2026-10-01 12:00）を返す。"""
    return NOW


def _web_now() -> datetime:
    """固定の今の時刻（2026-10-23 14:05）を返す。"""
    return WEB_NOW


def _touch(path: Path) -> Path:
    """親のフォルダごと空のファイルを作ってそのパスを返す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


# === save_recording ===


def test_save_recording(paths: AppPaths) -> None:
    """日付のフォルダへ書く（正常系）。"""
    from voice_paste.features.history.service import save_recording
    from voice_paste.shared.types import Recording

    # 準備
    recording = Recording(
        samples=np.zeros(SAMPLE_RATE, dtype=np.int16), sample_rate=SAMPLE_RATE, duration_sec=1.0
    )

    # 実行
    saved = save_recording("s1", recording, history_enabled=True, paths=paths, now=_now)

    # 検証
    assert saved == paths.history_dir / "20261001" / "20261001120000_s1.wav"
    sample_rate, samples = wavfile.read(saved)
    assert sample_rate == SAMPLE_RATE
    assert samples.dtype == np.int16


def test_save_recording_when_history_disabled(paths: AppPaths) -> None:
    """履歴を残さない設定は一時の音声へ書く（正常系）。"""
    from voice_paste.features.history.service import save_recording
    from voice_paste.shared.types import Recording

    # 準備
    recording = Recording(
        samples=np.zeros(SAMPLE_RATE, dtype=np.int16), sample_rate=SAMPLE_RATE, duration_sec=1.0
    )

    # 実行
    saved = save_recording("s1", recording, history_enabled=False, paths=paths, now=_now)

    # 検証
    assert saved == paths.tmp_dir / "s1.wav"
    assert saved.exists()
    assert not list(paths.history_dir.rglob("*.wav"))


def test_save_recording_when_segment(paths: AppPaths) -> None:
    """区間は通し番号を付けた名前で書き、同じ秒に書いても重ならない（正常系）。"""
    from voice_paste.features.history.service import save_recording
    from voice_paste.shared.types import Recording

    # 準備
    recording = Recording(
        samples=np.zeros(SAMPLE_RATE, dtype=np.int16), sample_rate=SAMPLE_RATE, duration_sec=1.0
    )

    # 実行: 履歴を残す設定と残さない設定で、同じ時刻に区間を 2 つずつ書く
    kept_first = save_recording("s1", recording, 1, history_enabled=True, paths=paths, now=_now)
    kept_second = save_recording("s1", recording, 2, history_enabled=True, paths=paths, now=_now)
    temporary_first = save_recording(
        "s1", recording, 1, history_enabled=False, paths=paths, now=_now
    )
    temporary_second = save_recording(
        "s1", recording, 2, history_enabled=False, paths=paths, now=_now
    )

    # 検証
    assert kept_first == paths.history_dir / "20261001" / "20261001120000_s1_1.wav"
    assert kept_second == paths.history_dir / "20261001" / "20261001120000_s1_2.wav"
    assert kept_first.exists()
    assert kept_second.exists()
    assert temporary_first == paths.tmp_dir / "s1_1.wav"
    assert temporary_second == paths.tmp_dir / "s1_2.wav"
    assert temporary_first.exists()
    assert temporary_second.exists()


# === append_text ===


def test_append_text(paths: AppPaths) -> None:
    """録音と同じ名前の .txt に書く（正常系）。"""
    from voice_paste.features.history.service import append_text

    # 準備
    audio_path = _touch(paths.history_dir / "20261001" / "20261001120000_s1.wav")

    # 実行
    append_text(audio_path, "今日は晴れ", paths=paths)

    # 検証
    text_path = paths.history_dir / "20261001" / "20261001120000_s1.txt"
    assert text_path.read_text(encoding="utf-8") == "今日は晴れ"


def test_append_text_when_temporary(paths: AppPaths) -> None:
    """一時の音声には書かない（正常系）。"""
    from voice_paste.features.history.service import append_text

    # 準備
    audio_path = _touch(paths.tmp_dir / "s1.wav")

    # 実行
    append_text(audio_path, "今日は晴れ", paths=paths)

    # 検証
    assert not list(paths.tmp_dir.glob("*.txt"))


# === discard_temporary ===


def test_discard_temporary(paths: AppPaths) -> None:
    """一時の音声を削除する（正常系）。"""
    from voice_paste.features.history.service import discard_temporary

    # 準備
    audio_path = _touch(paths.tmp_dir / "s1.wav")

    # 実行
    discard_temporary(audio_path, paths=paths)

    # 検証
    assert not audio_path.exists()


def test_discard_temporary_when_history(paths: AppPaths) -> None:
    """履歴の録音は削除しない（正常系）。"""
    from voice_paste.features.history.service import discard_temporary

    # 準備
    audio_path = _touch(paths.history_dir / "20261001" / "20261001120000_s1.wav")

    # 実行
    discard_temporary(audio_path, paths=paths)

    # 検証
    assert audio_path.exists()


# === purge_expired ===


def test_purge_expired(paths: AppPaths) -> None:
    """保持期間を過ぎた日付のフォルダだけ削除する（正常系）。"""
    from voice_paste.features.history.service import purge_expired

    # 準備
    for folder_name in ("20261001", "20260930", "20260929", "notes"):
        _touch(paths.history_dir / folder_name / "recording.wav")

    # 実行
    removed = purge_expired(
        retention_days=1, paths=paths, now=_now, active_session_ids=lambda: set()
    )

    # 検証
    assert removed == 1
    assert sorted(path.name for path in paths.history_dir.iterdir()) == [
        "20260930",
        "20261001",
        "notes",
    ]


def test_purge_expired_when_temporary_left(paths: AppPaths) -> None:
    """処理中でない一時の音声だけ削除する（正常系）。"""
    from voice_paste.features.history.service import purge_expired

    # 準備
    paths.history_dir.mkdir(parents=True)
    finished = _touch(paths.tmp_dir / "s1.wav")
    active = _touch(paths.tmp_dir / "s2.wav")

    # 実行
    purge_expired(retention_days=1, paths=paths, now=_now, active_session_ids=lambda: {"s2"})

    # 検証
    assert not finished.exists()
    assert active.exists()


def test_purge_expired_keeps_active_segments(paths: AppPaths) -> None:
    """処理中の連続録音の区間の一時の音声は残す（正常系）。"""
    from voice_paste.features.history.service import purge_expired

    # 準備: 処理中のセッション s2 の区間と、終わったセッション s1 の区間
    paths.history_dir.mkdir(parents=True)
    finished = _touch(paths.tmp_dir / "s1_1.wav")
    active = _touch(paths.tmp_dir / "s2_3.wav")

    # 実行
    purge_expired(retention_days=1, paths=paths, now=_now, active_session_ids=lambda: {"s2"})

    # 検証
    assert not finished.exists()
    assert active.exists()


def test_purge_expired_when_web_audio(paths: AppPaths) -> None:
    """期限を過ぎた日付のフォルダは WAV 以外の音声も削除する（正常系）。"""
    from voice_paste.features.history.service import purge_expired

    # 準備: 保持期間を過ぎた日付のフォルダにブラウザの音声（.webm）と起こした文字（.txt）
    paths.history_dir.mkdir(parents=True)
    expired_folder = paths.history_dir / "20260929"
    _touch(expired_folder / "20260929120000_web_job1.webm")
    _touch(expired_folder / "20260929120000_web_job1.txt")

    # 実行
    purge_expired(
        retention_days=1, paths=paths, now=_now, active_session_ids=lambda: set()
    )

    # 検証
    assert not expired_folder.exists()


# === store_web_audio ===


def test_store_web_audio(paths: AppPaths) -> None:
    """録れた形式のまま履歴へ移す（正常系）。"""
    from voice_paste.features.history.service import store_web_audio

    # 準備
    source = _touch(paths.tmp_dir / "web" / "job1.webm")
    source.write_bytes(b"webm-audio")

    # 実行
    stored = store_web_audio(
        "job1", source, history_enabled=True, paths=paths, now=_web_now
    )

    # 検証
    expected = paths.history_dir / "20261023" / "20261023140500_web_job1.webm"
    assert stored == expected
    assert expected.read_bytes() == b"webm-audio"
    assert not source.exists()


def test_store_web_audio_when_history_disabled(paths: AppPaths) -> None:
    """履歴を残さない設定なら移さない（正常系）。"""
    from voice_paste.features.history.service import store_web_audio

    # 準備
    source = _touch(paths.tmp_dir / "web" / "job1.webm")

    # 実行
    stored = store_web_audio(
        "job1", source, history_enabled=False, paths=paths, now=_web_now
    )

    # 検証
    assert stored == source
    assert source.exists()
    assert not paths.history_dir.exists()
