"""workflow の E2E テストの fixture（検証用のブランチを作って push し、終わりに消す）。"""

import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.e2e.workflow.helpers import BRANCH_PREFIX, REPO_ROOT, PrepareTree, run


@pytest.fixture
def branch_factory(request: pytest.FixtureRequest) -> Iterator[Callable[[PrepareTree], str]]:
    """今の HEAD から検証用のブランチを作り、作業ツリーを書き換えて push する関数を返す。"""
    created: list[tuple[str, Path]] = []

    def _create(prepare: PrepareTree) -> str:
        branch = f"{BRANCH_PREFIX}/{request.node.name}-{int(time.time())}"
        tree = Path(tempfile.mkdtemp(prefix="vp-e2e-workflow-"))
        shutil.rmtree(tree)
        run(["git", "worktree", "add", "-b", branch, str(tree), "HEAD"], REPO_ROOT)
        created.append((branch, tree))
        prepare(tree)
        run(["git", "add", "--all"], tree)
        run(["git", "commit", "-m", f"test: {request.node.name} の検証用のブランチ"], tree)
        run(["git", "push", "origin", branch], tree)
        return branch

    yield _create

    for branch, tree in reversed(created):
        subprocess.run(["git", "push", "origin", "--delete", branch], cwd=REPO_ROOT, capture_output=True)
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=REPO_ROOT, capture_output=True)
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, capture_output=True)
