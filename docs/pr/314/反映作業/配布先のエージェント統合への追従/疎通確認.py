"""配布先のリポジトリの agent_context.yaml を読めて、退避先を作れるかを確かめる。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import follow


def main() -> int:
    """引数のリポジトリを読むだけで確かめる。"""
    # 引数が git のリポジトリでない: 書き換える先が無い
    if not sys.argv[1:] or not (Path(sys.argv[1]) / ".git").exists():
        print("配布先のリポジトリ: failed")
        return 1
    repo = Path(sys.argv[1])
    print("配布先のリポジトリ: ok")
    path = repo / follow.AGENT_CONTEXT
    # agent_context.yaml が無い: 書き換えるのは .claude/agent-settings/ だけ
    if not path.is_file():
        print(f"{follow.AGENT_CONTEXT}: skipped")
    else:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
            print(f"{follow.AGENT_CONTEXT}: ok")
        except yaml.YAMLError:
            print(f"{follow.AGENT_CONTEXT}: failed")
            return 1
    git_dir = follow.backup_dir(repo).parent
    if os.access(git_dir, os.W_OK):
        print("退避先: ok")
        return 0
    print("退避先: failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
