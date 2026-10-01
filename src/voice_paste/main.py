"""起動の入口。引数を読み、置き場所を決めてログを設定し、設定を読む。"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from voice_paste.shared.constants import resolve_app_paths
from voice_paste.shared.env_migration import migrate_env
from voice_paste.shared.errors import SettingsError
from voice_paste.shared.logger import local_today, purge_old_logs, setup_logging
from voice_paste.shared.settings import load_settings, save_settings

logger = logging.getLogger(__name__)

STARTUP_LOG_LEVEL: str = "INFO"
"""設定を読むまでのログのレベル。"""

EXIT_OK: int = 0
"""正常終了の終了コード。"""

EXIT_FAILED: int = 1
"""起動に失敗した終了コード。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CliArgs:
    """`python -m voice_paste` に渡した引数。"""

    data_dir: Path | None
    migrate_env: Path | None


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


def main(argv: list[str] | None = None) -> int:
    """置き場所を決めてログを設定し、設定を読んでログに書いて終了コードを返す。"""
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

    # 6. 読んだ設定の要点をログに書く（API キーは書かない）
    enabled_outputs = [output.id for output in settings.outputs if output.enabled]
    logger.info(
        f"設定を読んだ（{paths.settings_file}、エンジン: {settings.transcription.engine}、"
        f"オンの出力先: {', '.join(enabled_outputs)}）"
    )
    return EXIT_OK
