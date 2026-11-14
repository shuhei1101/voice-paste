"""配布先のリポジトリの直下に rules.yaml があり、docs/rules.yaml が無いかを読むだけで確かめる。"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """2 つのファイルの有無を出す。"""
    if len(sys.argv) < 2:
        print("配布先のリポジトリ: failed")
        return 1
    repo = Path(sys.argv[1])
    old, new = (repo / "docs" / "rules.yaml").is_file(), (repo / "rules.yaml").is_file()
    ok = new and not old
    print(f"索引（rules.yaml={new} / docs/rules.yaml={old}）: {'ok' if ok else 'failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
