"""配布先のリポジトリで、3 つのエージェントに割り当てた資料を planner・tester へ割り当て直し、3 つのエージェントの設定を削除する。"""

from __future__ import annotations

import difflib
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import follow


def _reassigned(names: list[str]) -> list[str]:
    """エージェント名を割り当て直し、重なった名前を最初の 1 つに畳んだ一覧を返す。"""
    return list(dict.fromkeys(follow.REASSIGN.get(name, name) for name in names))


def verify(before: str, after: str) -> bool:
    """書き換えた後の本文が読め、エージェント名の割り当て直しのほかは変わっていないかを返す。"""
    old_docs = (yaml.safe_load(before) or {}).get("docs") or []
    new_docs = (yaml.safe_load(after) or {}).get("docs") or []
    # 資料の数が同じで、各資料の割り当て以外の値と、割り当てを割り当て直した結果が一致すること
    if len(old_docs) != len(new_docs):
        return False
    keys = ("full_text", "index_only")
    for old, new in zip(old_docs, new_docs, strict=True):
        expected = {k: _reassigned(v) if k in keys and v else v for k, v in old.items()}
        if expected != new:
            return False
    return True


def main() -> int:
    """前提確認 → 計画 → 適用の順に配布先を書き換える。"""
    dry_run = "--dry-run" in sys.argv[2:]
    # 前提確認
    if not sys.argv[1:] or not (Path(sys.argv[1]) / ".git").exists():
        print("前提確認: failed")
        return 1
    repo = Path(sys.argv[1])
    print("前提確認: ok")
    backup = follow.backup_dir(repo)
    print(f"退避先: {backup}")
    # 計画（--dry-run もここを通る）
    path = repo / follow.AGENT_CONTEXT
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    after = follow.plan_agent_context(before)
    removed = [name for name in follow.AGENT_SETTINGS if (repo / name).is_file()]
    if before == after and not removed:
        print("エージェント統合への追従: skipped")
        return 0
    for name in removed:
        print(f"消すファイル: {repo / name}")
    sys.stdout.writelines(
        difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), str(path), str(path), n=1
        )
    )
    if dry_run:
        print("エージェント統合への追従: changed")
        return 0
    # 適用（検証 → 退避 → 削除・置き換え）
    if before != after and not verify(before, after):
        print(f"{follow.AGENT_CONTEXT} の検証: failed")
        return 1
    print("検証: ok")
    changed = [*removed, *([follow.AGENT_CONTEXT] if before != after else [])]
    for name in changed:
        (backup / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, backup / name)
    for name in removed:
        (repo / name).unlink()
        print(f"{name} の削除: changed")
    if before != after:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            tmp.write(after)
        shutil.copymode(path, tmp.name)
        Path(tmp.name).replace(path)
        print(f"{follow.AGENT_CONTEXT} の書き換え: changed")
    print("エージェント統合への追従: changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
