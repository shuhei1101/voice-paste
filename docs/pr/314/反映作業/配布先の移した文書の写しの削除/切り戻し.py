"""実行で退避した写しと索引を、配布先のリポジトリへ戻す。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copies


def main() -> int:
    """退避したファイルを元の場所へ書き戻す。"""
    if not sys.argv[1:] or not copies.backup_dir(Path(sys.argv[1])).is_dir():
        print("退避したファイル: failed")
        return 1
    repo = Path(sys.argv[1])
    backup = copies.backup_dir(repo)
    for file in sorted(p for p in backup.rglob("*") if p.is_file()):
        target = repo / file.relative_to(backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        print(f"{file.relative_to(backup)}: changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
