"""配布先のリポジトリと、移した文書の一覧に、読み取りだけでつながるかを確かめる。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copies


def main() -> int:
    """対象ごとに結果の行を出す。"""
    repo_ok = bool(sys.argv[1:]) and (Path(sys.argv[1]) / ".git").exists()
    list_ok = copies.LIST.is_file() and bool(copies.targets())
    print(f"配布先のリポジトリ: {'ok' if repo_ok else 'failed'}")
    print(f"移した文書の一覧: {'ok' if list_ok else 'failed'}")
    return 0 if repo_ok and list_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
