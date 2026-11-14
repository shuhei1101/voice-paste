"""配布先のリポジトリに残った、移した文書の写しと、それを指す索引のエントリを見つける共通の処理。

写しは、内容が AI Monitor の過去のどれかの版と同じファイルに限る（同じ名前でもプロジェクトが書き換えたファイルは残す）。
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path

LIST = Path(__file__).resolve().parent / "対象一覧.tsv"
INDEXES = ("rules.yaml", "docs/rules.yaml")
ENTRY_HEAD = re.compile(r"^  - ")
RULE_LINE = re.compile(r"^\s*-?\s*rule:\s*(\S.*?)\s*$")
BACKUP_NAME = "ai-monitor-pr2941-backup"
COMMENT_MARK = "#"


def targets() -> dict[str, set[str]]:
    """移した文書のパス → AI Monitor が持ったその文書の blob のハッシュの集合を返す。"""
    result: dict[str, set[str]] = {}
    for line in LIST.read_text(encoding="utf-8").splitlines():
        if line.startswith(COMMENT_MARK):
            continue
        path, hashes = line.split("\t")
        result[path] = set(hashes.split(","))
    return result


def backup_dir(repo: Path) -> Path:
    """退避先を返す。worktree でも書ける git のディレクトリ（worktree なら .git/worktrees/{名前}）の配下に置く。"""
    git_dir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(git_dir) / BACKUP_NAME


def blob_hash(file: Path) -> str:
    """ファイルの git の blob のハッシュを返す。"""
    return subprocess.run(
        ["git", "hash-object", "--", str(file)], capture_output=True, text=True, check=True
    ).stdout.strip()


def find_copies(repo: Path) -> list[str]:
    """配布先にある、内容が AI Monitor の版と同じ移した文書のパスを返す。"""
    return [
        path
        for path, hashes in targets().items()
        if (repo / path).is_file() and blob_hash(repo / path) in hashes
    ]


def rule_path(index: str, value: str) -> str | None:
    """索引の rule の値を、リポジトリの直下からのパスに直す（相対パス以外は None）。"""
    if value.startswith(("/", "http://", "https://", "!{", '"', "'")):
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(index), value))


def plan_index(index: str, text: str, removed: set[str]) -> str:
    """消すファイルを指すエントリを除いた索引の本文を返す。"""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        # エントリの頭: そのエントリの rule が消すファイルを指すかで、エントリごと残すか決める
        if ENTRY_HEAD.match(line):
            match = RULE_LINE.match(line)
            skipping = bool(match) and rule_path(index, match.group(1)) in removed
        # エントリの外（インデントの無い行）: 除くのを止める
        elif not line.startswith(" "):
            skipping = False
        if not skipping:
            out.append(line)
    return "".join(out)


def dangling_rules(repo: Path) -> list[str]:
    """索引のうち、移した文書のパスを指すのにファイルが無いエントリの rule を返す。"""
    moved = set(targets())
    found: list[str] = []
    for index in INDEXES:
        if not (repo / index).is_file():
            continue
        for line in (repo / index).read_text(encoding="utf-8").splitlines():
            match = RULE_LINE.match(line)
            path = rule_path(index, match.group(1)) if match else None
            if path in moved and not (repo / path).is_file():
                found.append(f"{index}: {match.group(1)}")
    return found
