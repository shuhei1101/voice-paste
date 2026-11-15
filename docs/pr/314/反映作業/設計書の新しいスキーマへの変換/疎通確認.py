"""AI Monitor の設計書のコマンドと、knowledge のスキーマのリビジョンに読み取りだけでつながるかを確かめる。"""

import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import AI_MONITOR, KNOWLEDGE, TO_REF, design_docs, fail  # noqa: E402

code, stdout, stderr, command = design_docs(["convert", "--help"], Path.cwd())
if code != 0:
    fail("AI Monitor の設計書のコマンド", command, stderr or stdout)
print(f"AI Monitor の設計書のコマンド: ok（{AI_MONITOR}）")

command = ["git", "-C", str(KNOWLEDGE), "rev-parse", "--verify", "--quiet", f"refs/tags/{TO_REF}"]
done = subprocess.run(command, capture_output=True, text=True, check=False)
if done.returncode != 0:
    fail("knowledge のスキーマのリビジョン", command, done.stderr)
print(f"knowledge のスキーマのリビジョン: ok（{TO_REF}）")
