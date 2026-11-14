"""配布先のリポジトリと書き換える対象のファイルを読めるかを確かめる。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from common import TARGETS, repo_root  # noqa: E402

root, _ = repo_root([sys.argv[0], *sys.argv[1:2]])
print("配布先のリポジトリ: ok")
for name in TARGETS:
    path = root / name
    print(f"{name}: {'ok' if path.is_file() else 'skipped'}")
