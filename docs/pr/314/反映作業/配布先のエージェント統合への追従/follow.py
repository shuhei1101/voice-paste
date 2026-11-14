"""配布先のエージェント統合への追従が使う、書き換え先と退避先と agent_context.yaml の書き換え。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

AGENT_CONTEXT = "agent_context.yaml"
# 割り当て直す先（implementer・designer は planner、operator は tester）
REASSIGN = {"implementer": "planner", "designer": "planner", "operator": "tester"}
AGENT_SETTINGS = tuple(f".claude/agent-settings/{name}.json" for name in REASSIGN)
BACKUP_NAME = "ai-monitor-pr3137-backup"
# full_text・index_only のフロースタイルの一覧の行
_FLOW = re.compile(r"^(?P<head>\s*(?:full_text|index_only):\s*)\[(?P<items>[^\]]*)\](?P<tail>.*)$")
# full_text・index_only のブロックスタイルの一覧の見出しの行
_BLOCK_HEAD = re.compile(r"^\s*(?:full_text|index_only):\s*(?:#.*)?$")
_BLOCK_ITEM = re.compile(r"^(?P<head>\s*-\s*)(?P<name>[\"']?[\w*-]+[\"']?)(?P<tail>\s*(?:#.*)?)$")


def backup_dir(repo: Path) -> Path:
    """退避先を返す。worktree でも書ける git のディレクトリ（worktree なら .git/worktrees/{名前}）の配下に置く。"""
    git_dir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(git_dir) / BACKUP_NAME


def _rename(names: list[str]) -> list[str]:
    """エージェント名を割り当て直し、重なった名前を最初の 1 つに畳む。"""
    out: list[str] = []
    for name in names:
        bare = name.strip("\"'")
        new = REASSIGN.get(bare, bare)
        renamed = name if new == bare else name.replace(bare, new)
        if renamed.strip("\"'") not in [o.strip("\"'") for o in out]:
            out.append(renamed)
    return out


def plan_agent_context(text: str) -> str:
    """full_text・index_only の一覧の 3 つのエージェント名を割り当て直した本文を返す。"""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_block = False
    seen: list[str] = []
    for line in lines:
        body = line.rstrip("\n")
        newline = line[len(body) :]
        flow = _FLOW.match(body)
        # フロースタイルの一覧: 1 行の中で割り当て直す
        if flow:
            items = [item.strip() for item in flow["items"].split(",") if item.strip()]
            out.append(f"{flow['head']}[{', '.join(_rename(items))}]{flow['tail']}{newline}")
            in_block = False
            continue
        # ブロックスタイルの一覧の見出し: 続く `- 名前` の行を割り当て直す
        if _BLOCK_HEAD.match(body):
            out.append(line)
            in_block, seen = True, []
            continue
        item = _BLOCK_ITEM.match(body) if in_block else None
        if item:
            renamed = _rename([*seen, item["name"]])
            # 割り当て直した名前が既に一覧にある: 行を落とす
            if len(renamed) == len(seen):
                continue
            seen = renamed
            out.append(f"{item['head']}{renamed[-1]}{item['tail']}{newline}")
            continue
        in_block = in_block and not body.strip()
        out.append(line)
    return "".join(out)
