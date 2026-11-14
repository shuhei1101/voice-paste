"""配布先のリポジトリの agent_context.yaml と .claude/agent-settings/ に、3 つのエージェントが無いかを確かめる。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import follow


def main() -> int:
    """引数のリポジトリを読むだけで確かめ、残っているものを出す。"""
    repo = Path(sys.argv[1])
    path = repo / follow.AGENT_CONTEXT
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    left = sorted(
        {
            f"{doc.get('path')} の {name}"
            for doc in (data or {}).get("docs") or []
            for key in ("full_text", "index_only")
            for name in doc.get(key) or []
            if name in follow.REASSIGN
        }
    )
    left += [name for name in follow.AGENT_SETTINGS if (repo / name).exists()]
    # 残っていない: 効いている
    if not left:
        print("エージェント統合への追従: ok")
        return 0
    print(f"エージェント統合への追従: failed（残っている: {'、'.join(left)}）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
