"""対象のリポジトリと mdmark の設定を、読むだけで確かめる。"""

from __future__ import annotations

import sys

from common import TARGET, fail, repo_from_args, yaml_rt

repo, _ = repo_from_args(sys.argv, allow_dry_run=False)
print("対象のリポジトリ: ok")
path = repo / TARGET
# 設定が無ければ作るので、読めるかだけを確かめる
if not path.exists():
    print(f"{TARGET}: ok（無い。実行で作る）")
    sys.exit(0)
try:
    doc = yaml_rt().load(path.read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001 - 読めない理由をそのまま出す
    fail(TARGET, str(exc))
if doc is not None and not isinstance(doc, dict):
    fail(TARGET, "最上位がオブジェクトではありません")
print(f"{TARGET}: ok")
