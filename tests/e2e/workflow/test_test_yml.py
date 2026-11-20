"""workflow test.yml のフローを、本物の GitHub Actions で起動して確かめる E2E テスト（IF-15）。"""

import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.e2e.workflow.helpers import REPO_ROOT, PrepareTree, run

pytestmark = pytest.mark.real_machine

WORKFLOW: str = "test.yml"
"""起動する workflow のファイル。"""

STEPS: list[str] = ["ブランチを取得する", "uv を入れる", "Python の依存を入れる", "テストを回す", "ログを成果物に上げる"]
"""workflow のファイルの step の name（図の step と同じ）。"""

ARTIFACT: str = "test-log"
"""テストのログの成果物の名前。"""


@dataclass(frozen=True)
class RunResult:
    """workflow の実行の結論と、step ごとの結論と、成果物のログ。"""

    conclusion: str
    steps: dict[str, str]
    log: str | None


def replace_layer(layer: str, body: str) -> PrepareTree:
    """層のフォルダの中身を、本文 body のテスト 1 件だけに差し替える関数を返す。"""

    def _prepare(tree: Path) -> None:
        folder = tree / "tests" / layer
        shutil.rmtree(folder)
        folder.mkdir()
        (folder / "__init__.py").write_text("", encoding="utf-8")
        (folder / "test_e2e_workflow.py").write_text(body, encoding="utf-8")

    return _prepare


def break_lock(tree: Path) -> None:
    """`uv sync --frozen` が失敗するよう uv.lock を壊す。"""
    (tree / "uv.lock").write_text("broken = [\n", encoding="utf-8")


VISIBLE_RETRIES: int = 10
"""起動した実行を API で参照できるまで、1 秒ごとに確かめる回数（TP-1 の `run_runner` と同じ）。"""


def wait_until_visible(run_id: str) -> None:
    """起動した実行を API で参照できるまで待つ（参照できる前の `gh run watch` はすぐ終わるため）。"""
    for _ in range(VISIBLE_RETRIES):
        visible = subprocess.run(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}?exclude_pull_requests=true"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if visible.returncode == 0:
            return
        time.sleep(1)
    pytest.fail(f"実行 {run_id} を {VISIBLE_RETRIES} 秒参照できません")


def dispatch(branch: str, layer: str, paths: str | None = None) -> RunResult:
    """workflow を起動して終わるまで待ち、結論・step ごとの結論・成果物のログを返す。"""
    args = ["gh", "workflow", "run", WORKFLOW, "--ref", branch, "-f", f"layer={layer}"]
    if paths is not None:
        args += ["-f", f"paths={paths}"]
    out = run(args, REPO_ROOT)
    match = re.search(r"https://\S*/actions/runs/(\d+)", out)
    assert match is not None, out
    run_id = match.group(1)
    wait_until_visible(run_id)
    subprocess.run(["gh", "run", "watch", run_id, "--exit-status"], cwd=REPO_ROOT, capture_output=True)
    view = json.loads(run(["gh", "run", "view", run_id, "--json", "conclusion,jobs"], REPO_ROOT))
    steps = {step["name"]: step["conclusion"] for job in view["jobs"] for step in job["steps"] if step["name"] in STEPS}
    log: str | None = None
    with tempfile.TemporaryDirectory() as tmp:
        downloaded = subprocess.run(
            ["gh", "run", "download", run_id, "-n", ARTIFACT, "-D", tmp], cwd=REPO_ROOT, capture_output=True
        )
        if downloaded.returncode == 0:
            log = (Path(tmp) / "test.log").read_text(encoding="utf-8", errors="replace")
    return RunResult(conclusion=view["conclusion"], steps=steps, log=log)


PASS_BODY: str = "def test_pass() -> None:\n    assert True\n"
FAIL_BODY: str = "def test_fail() -> None:\n    assert False\n"
SLEEP_BODY: str = "import time\n\n\ndef test_sleep() -> None:\n    time.sleep(400)\n"

ALL_SUCCESS: dict[str, str] = dict.fromkeys(STEPS, "success")
"""全ての step が成功したときの step ごとの結論。"""

TEST_STEP_FAILED: dict[str, str] = {**ALL_SUCCESS, "テストを回す": "failure"}
"""step「テストを回す」だけが失敗したときの step ごとの結論。"""

SETUP_FAILED: dict[str, str] = {
    **ALL_SUCCESS,
    "Python の依存を入れる": "failure",
    "テストを回す": "skipped",
}
"""step「Python の依存を入れる」が失敗したときの step ごとの結論。"""


def test_normal(branch_factory: Callable[[PrepareTree], str]) -> None:
    """正常系: 単体テストの層の全件が pass して成功で終わる。"""
    result = dispatch(branch_factory(replace_layer("unit", PASS_BODY)), "unit")
    assert result.conclusion == "success"
    assert result.steps == ALL_SUCCESS
    assert result.log is not None and re.search(r"=+ 1 passed", result.log)


def test_normal_when_integration(branch_factory: Callable[[PrepareTree], str]) -> None:
    """正常系（結合テストの層）: 結合テストの層のフォルダを指定し、層の全件が pass して成功で終わる。"""
    result = dispatch(branch_factory(replace_layer("integration", PASS_BODY)), "integration", "tests/integration")
    assert result.conclusion == "success"
    assert result.steps == ALL_SUCCESS
    assert result.log is not None and re.search(r"=+ 1 passed", result.log)


def add_fail_file(tree: Path) -> None:
    """`tests/integration/` に必ず fail するテストのファイルを加える。"""
    (tree / "tests" / "integration" / "test_e2e_fail.py").write_text(FAIL_BODY, encoding="utf-8")


def test_normal_when_paths_given(branch_factory: Callable[[PrepareTree], str]) -> None:
    """正常系（テストのパスを指定）: 指定したテストのファイルだけを回し、全件 pass して成功で終わる。"""

    def _prepare(tree: Path) -> None:
        replace_layer("integration", PASS_BODY)(tree)
        add_fail_file(tree)

    result = dispatch(branch_factory(_prepare), "integration", "tests/integration/test_e2e_workflow.py")
    assert result.conclusion == "success"
    assert result.steps == ALL_SUCCESS
    assert result.log is not None and "test_pass" in result.log and re.search(r"=+ 1 passed", result.log)
    assert "test_fail" not in result.log


def test_error_when_test_fails(branch_factory: Callable[[PrepareTree], str]) -> None:
    """異常系（テストの fail・failure）: 層の全件に fail があり、ログを上げて失敗で終わる。"""
    result = dispatch(branch_factory(replace_layer("unit", FAIL_BODY)), "unit")
    assert result.conclusion == "failure"
    assert result.steps == TEST_STEP_FAILED
    assert result.log is not None and "test_fail" in result.log and re.search(r"=+ 1 failed", result.log)


def test_error_when_test_times_out(branch_factory: Callable[[PrepareTree], str]) -> None:
    """異常系（テストが上限の時間を超えた・failure）: テスト 1 件が上限の時間を超えて止められ、ログを上げて失敗で終わる。"""
    result = dispatch(branch_factory(replace_layer("unit", SLEEP_BODY)), "unit")
    assert result.conclusion == "failure"
    assert result.steps == TEST_STEP_FAILED
    assert result.log is not None and "Timeout" in result.log


def test_error_when_setup_fails(branch_factory: Callable[[PrepareTree], str]) -> None:
    """異常系（道具の導入に失敗・failure）: Python の依存の導入に失敗し、層の全件を回さずにログを上げて失敗で終わる。"""
    result = dispatch(branch_factory(break_lock), "unit")
    assert result.conclusion == "failure"
    assert result.steps == SETUP_FAILED


def test_error_when_path_outside_layer(branch_factory: Callable[[PrepareTree], str]) -> None:
    """異常系（層の外のパス・failure）: 層のフォルダの外のパスを含めて指定され、テストを回さずにログを上げて失敗で終わる。"""
    result = dispatch(
        branch_factory(replace_layer("integration", PASS_BODY)),
        "integration",
        "tests/integration/test_e2e_workflow.py tests/integration/../unit",
    )
    assert result.conclusion == "failure"
    assert result.steps == TEST_STEP_FAILED
    assert result.log is not None and "tests/integration/../unit" in result.log
    assert not re.search(r"=+ \d+ (passed|failed)", result.log)
