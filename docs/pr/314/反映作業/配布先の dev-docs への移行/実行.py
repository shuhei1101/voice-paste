"""配布先が dev-docs の配信元として登録され、共通設定に撤去した設計書のツールが残っていないことを確かめる。

配信元の dev-docs.yaml と端末の設定への登録は、`/dev-docs:setup {配布先のパス}` が判断を伴って作るため、無ければ failed で止める。
"""

import subprocess
import sys
from pathlib import Path

import yaml

DEV_DOCS_SETTINGS = Path.home() / ".config/dev-docs/settings.yaml"
AI_MONITOR_SETTINGS = Path.home() / ".config/ai-monitor/settings.yaml"
REMOVED_TOOLS = (
    "search_design_docs",
    "read_design_doc",
    "check_design_doc_refs",
    "diff_design_docs",
    "get_generated_design_docs",
    "list_design_doc_tags",
    "replace_in_design_docs",
    "write_design_doc",
)


def main() -> int:
    # 前提確認
    if len(sys.argv) < 2:
        print("前提確認: failed（対象のリポジトリの場所が無い）")
        return 1
    try:
        top = subprocess.run(
            ["git", "-C", sys.argv[1], "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        print("前提確認: failed（リポジトリでない）")
        return 1
    repo = Path(top)
    print("前提確認: ok")

    # 計画（--dry-run もここを通る。このスクリプトは書き換えないため適用は無い）
    status = 0
    if (repo / "dev-docs.yaml").is_file():
        print("dev-docs.yaml: ok")
    else:
        print(f"dev-docs.yaml: failed（/dev-docs:setup {repo} で作る）")
        status = 1
    sources = yaml.safe_load(DEV_DOCS_SETTINGS.read_text(encoding="utf-8"))["sources"]
    root = repo.parent.parent.parent if repo.parent.name == "worktrees" else repo
    configs = [Path(source["config"]) for source in sources]
    if any(config.is_relative_to(root) and config.name == "dev-docs.yaml" for config in configs):
        print("配信元の登録: ok")
    else:
        print(f"配信元の登録: failed（/dev-docs:setup {repo} で登録する）")
        status = 1
    settings_text = AI_MONITOR_SETTINGS.read_text(encoding="utf-8")
    left = [name for name in REMOVED_TOOLS if name in settings_text]
    if left:
        print("共通設定の撤去した設計書のツール: failed（agents[].mcp_tools から外す: " + ", ".join(left) + "）")
        status = 1
    else:
        print("共通設定の撤去した設計書のツール: ok")
    return status


if __name__ == "__main__":
    sys.exit(main())
