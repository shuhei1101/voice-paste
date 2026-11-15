"""workflow の E2E テストが共有するリポジトリの場所とコマンドの実行。"""

import subprocess
from collections.abc import Callable
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
"""リポジトリの直下。"""

BRANCH_PREFIX: str = "e2e/workflow"
"""検証用のブランチの名前の頭。"""

PrepareTree = Callable[[Path], None]
"""検証用のブランチの作業ツリーを書き換える関数の型。"""


def run(args: list[str], cwd: Path) -> str:
    """コマンドを実行し、標準出力を返す（失敗したら例外にする）。"""
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout
