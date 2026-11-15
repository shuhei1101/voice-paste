"""実行で退避した設計書・dev-docs.yaml・files.yml を元へ戻す。"""

import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import BACKUP_NAME, fail, git_dir  # noqa: E402

ROOT = Path.cwd()
backup = git_dir(ROOT) / BACKUP_NAME
manifest = backup / "files.txt"
if not manifest.is_file():
    fail("退避したファイル", stderr=f"{manifest} が無い")
files = [Path(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line]
missing = [str(rel) for rel in files if not (backup / rel).is_file()]
if missing:
    fail("退避したファイル", stderr="\n".join(missing))
print(f"退避したファイル: ok（{len(files)} ファイル）")
for rel in files:
    shutil.copy2(backup / rel, ROOT / rel)
print("設計書の書き戻し: changed")
