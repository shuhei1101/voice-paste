"""配布先の dev-docs.yaml と knowledge のクローンのタグを読めるかを確かめる。"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REF, fail, knowledge_clone, parse_args  # noqa: E402

args = parse_args(sys.argv[1:])
if args is None:
    fail("前提確認", "第 1 引数に配布先のリポジトリの直下を渡してください")
root, _ = args
if not (root / "dev-docs.yaml").is_file():
    fail("dev-docs.yaml", f"{root / 'dev-docs.yaml'} がありません")
print("dev-docs.yaml: ok")
# knowledge のクローンは、AI Monitor と同じく端末の project-index の設定から引く
knowledge = knowledge_clone()
if knowledge is None:
    fail("knowledge のクローン", "端末の project-index の設定に knowledge の配信元がありません")
print("knowledge のクローン: ok")
result = subprocess.run(["git", "-C", str(knowledge), "rev-parse", "--verify", f"{REF}^{{commit}}"], capture_output=True, text=True, check=False)
if result.returncode != 0:
    fail("knowledge のタグ", result.stderr)
print("knowledge のタグ: ok")
