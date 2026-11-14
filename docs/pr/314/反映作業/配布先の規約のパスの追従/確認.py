"""配布先の rules.yaml・agent_context.yaml に変換前の規約などの .md のパスが残っていないかを確かめる。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from common import MAPPING, TARGETS, repo_root  # noqa: E402

root, _ = repo_root([sys.argv[0], *sys.argv[1:2]])
failed = False
for name in TARGETS:
    path = root / name
    if not path.is_file():
        print(f"{name}: skipped")
        continue
    left = [old for old in MAPPING if old in path.read_text(encoding="utf-8")]
    print(f"{name}: {'failed' if left else 'ok'}")
    if left:
        print(f"残っているパス: {left}")
        failed = True
sys.exit(1 if failed else 0)
