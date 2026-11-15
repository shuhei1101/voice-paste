"""配布先のリポジトリに、移した文書の写しと、無いファイルを指す索引のエントリが残っていないかを読むだけで確かめる。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copies


def main() -> int:
    """残った写しと、無いファイルを指すエントリを出す。"""
    if not sys.argv[1:]:
        print("配布先のリポジトリ: failed")
        return 1
    repo = Path(sys.argv[1])
    found, dangling = copies.find_copies(repo), copies.dangling_rules(repo)
    print(f"移した文書の写し（{found or 'なし'}）: {'failed' if found else 'ok'}")
    print(f"無いファイルを指すエントリ（{dangling or 'なし'}）: {'failed' if dangling else 'ok'}")
    return 1 if found or dangling else 0


if __name__ == "__main__":
    raise SystemExit(main())
