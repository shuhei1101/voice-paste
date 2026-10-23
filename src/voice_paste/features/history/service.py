"""録音の保存・ブラウザの音声の保存・起こした文字の書き足し・一時の音声の削除・古い履歴の削除。"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from scipy.io import wavfile

from voice_paste.shared.constants import AppPaths
from voice_paste.shared.types import Recording

logger = logging.getLogger(__name__)

DATE_FOLDER_FORMAT: str = "%Y%m%d"
"""履歴の日付のフォルダの名前の形。"""

TIMESTAMP_FORMAT: str = "%Y%m%d%H%M%S"
"""録音のファイル名の先頭に付ける日時の形。"""

AUDIO_SUFFIX: str = ".wav"
"""録音のファイルの拡張子。"""

TEXT_SUFFIX: str = ".txt"
"""起こした文字のファイルの拡張子。"""

SEGMENT_SEPARATOR: str = "_"
"""ファイル名で、session_id と連続録音の区間の通し番号を区切る文字。"""


def _is_temporary(audio_path: Path, paths: AppPaths) -> bool:
    """録音が一時の音声（`tmp/` の下）か。"""
    return audio_path.is_relative_to(paths.tmp_dir)


def _parse_date_folder(name: str) -> datetime | None:
    """履歴の日付のフォルダの名前（`YYYYMMDD`）を日付にする。日付でなければ None を返す。"""
    # strptime は桁の足りない名前（2026101 など）も受けるため、桁数も確かめる
    if len(name) != len("YYYYMMDD"):
        return None
    try:
        return datetime.strptime(name, DATE_FOLDER_FORMAT)  # noqa: DTZ007 日付だけを比べる
    except ValueError:
        return None


def save_recording(
    session_id: str,
    recording: Recording,
    segment_number: int | None = None,
    *,
    history_enabled: bool,
    paths: AppPaths,
    now: Callable[[], datetime],
) -> Path:
    """確定した録音を履歴か一時の音声へ WAV で書き、書いたパスを返す。連続録音の区間は通し番号を付けた名前で書く。"""
    # 1. 履歴を残す設定かで書き先を決める（区間なら、拡張子の前に通し番号を付ける）
    segment_suffix = "" if segment_number is None else f"{SEGMENT_SEPARATOR}{segment_number}"
    if history_enabled:
        # 残す: 日付のフォルダの下に、日時と session_id の名前で書く
        current = now()
        audio_path = (
            paths.history_dir
            / current.strftime(DATE_FOLDER_FORMAT)
            / f"{current.strftime(TIMESTAMP_FORMAT)}_{session_id}{segment_suffix}{AUDIO_SUFFIX}"
        )
    else:
        # 残さない: 一時の音声のフォルダへ書く
        audio_path = paths.tmp_dir / f"{session_id}{segment_suffix}{AUDIO_SUFFIX}"

    # 2. 書き先のフォルダを作り、録音をモノラルの 16 bit の WAV で書く
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(audio_path, recording.sample_rate, recording.samples)
    logger.info(f"録音を残した（{audio_path}・{recording.duration_sec:.1f} 秒）")
    return audio_path


def store_web_audio(
    job_id: str,
    source: Path,
    *,
    history_enabled: bool,
    paths: AppPaths,
    now: Callable[[], datetime],
) -> Path:
    """ブラウザから受けた音声の一時のファイルを、履歴を残す設定なら録れた形式の拡張子のまま履歴へ移し、文字起こしに渡すパスを返す。"""
    # 1. 履歴を残さない設定なら、一時のファイルのまま返す（起こし終えた後に discard_temporary が消す）
    if not history_enabled:
        return source

    # 2. 日付のフォルダの下へ、日時とジョブの ID の名前で移す（拡張子は録れた形式のまま）
    current = now()
    stored = (
        paths.history_dir
        / current.strftime(DATE_FOLDER_FORMAT)
        / f"{current.strftime(TIMESTAMP_FORMAT)}_web_{job_id}{source.suffix}"
    )
    stored.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(source, stored)
    logger.info(f"ブラウザの音声を残した（{stored}）")
    return stored


def append_text(audio_path: Path, text: str, *, paths: AppPaths) -> None:
    """録音と同じ名前の .txt へ起こした文字を書く。一時の音声なら何もしない。"""
    # 1. 一時の音声（履歴を残さない設定）なら何もしない
    if _is_temporary(audio_path, paths):
        return

    # 2. 録音と同じフォルダ・同じ名前の .txt へ UTF-8 で書く（空の文字も書く）
    audio_path.with_suffix(TEXT_SUFFIX).write_text(text, encoding="utf-8")


def discard_temporary(audio_path: Path, *, paths: AppPaths) -> None:
    """処理を終えた録音が一時の音声なら消す。履歴の録音なら何もしない。"""
    # 1. 一時の音声でなければ何もしない（履歴の録音）
    if not _is_temporary(audio_path, paths):
        return

    # 2. 録音を消す（既に無ければ何もしない）
    try:
        audio_path.unlink(missing_ok=True)
    except OSError as error:
        # 消せない: 例外を出さずに残す（古い履歴の削除が掃除する）
        logger.warning(f"一時の音声を消せなかった（{audio_path}・{error}）")


def _purge_expired_folders(retention_days: int, paths: AppPaths, now: datetime) -> int:
    """history/ の下の、保持期間を過ぎた日付のフォルダを消し、消した数を返す。"""
    if not paths.history_dir.exists():
        return 0

    oldest_kept = now.date() - timedelta(days=retention_days)
    removed = 0
    for folder in paths.history_dir.iterdir():
        folder_date = _parse_date_folder(folder.name)
        # 日付でない名前・日付のフォルダでないものは残す
        if folder_date is None or not folder.is_dir():
            continue
        # 保持期間の中の日付は残す
        if folder_date.date() >= oldest_kept:
            continue
        try:
            shutil.rmtree(folder)
        except OSError as error:
            # 消せない: 残して次へ進む
            logger.warning(f"古い履歴を消せなかった（{folder}・{error}）")
            continue
        removed += 1
    return removed


def _purge_leftover_temporary(paths: AppPaths, active_session_ids: set[str]) -> None:
    """tmp/ の下に取り残された一時の音声のうち、処理中のセッションでないものを消す。"""
    if not paths.tmp_dir.exists():
        return

    for audio_path in paths.tmp_dir.glob(f"*{AUDIO_SUFFIX}"):
        # ファイル名の session_id（区間なら区切り文字より前）が処理中のセッションにあれば残す
        if audio_path.stem.split(SEGMENT_SEPARATOR)[0] in active_session_ids:
            continue
        try:
            audio_path.unlink()
        except OSError as error:
            # 消せない: 残して次へ進む
            logger.warning(f"古い履歴を消せなかった（{audio_path}・{error}）")


def purge_expired(
    *,
    retention_days: int,
    paths: AppPaths,
    now: Callable[[], datetime],
    active_session_ids: Callable[[], set[str]],
) -> int:
    """保持期間を過ぎた履歴のフォルダと、取り残された一時の音声を消し、消したフォルダの数を返す。"""
    # 1. 日付が保持期間を過ぎた履歴のフォルダを消す
    removed = _purge_expired_folders(retention_days, paths, now())
    logger.info(f"古い履歴を消した（{removed} 件）")

    # 2. 取り残された一時の音声のうち、処理中のセッションでないものを消す
    _purge_leftover_temporary(paths, active_session_ids())
    return removed
