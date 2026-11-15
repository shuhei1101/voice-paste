"""第 1 引数の配布先のリポジトリと、その docs/rules.yaml を読めるかを確かめる。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """リポジトリであることと、索引の有無を読むだけで確かめる。"""
    if len(sys.argv) < 2 or not (Path(sys.argv[1]) / ".git").exists():
        print("配布先のリポジトリ: failed")
        return 1
    repo = Path(sys.argv[1])
    result = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True)
    print(f"配布先のリポジトリ: {'ok' if result.returncode == 0 else 'failed'}")
    old, new = repo / "docs" / "rules.yaml", repo / "rules.yaml"
    print(f"索引（docs/rules.yaml={old.is_file()} / rules.yaml={new.is_file()}）: ok")
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
