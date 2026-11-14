"""各プロジェクトのスキーマの参照への移行の共通の定義。"""

import re
import sys
from pathlib import Path

REF = "design-schemas/v8.1.0"
SOURCE = "knowledge"
# AI Monitor から配ったスキーマのコピーの名前 → knowledge のスキーマのパス（None は参照の行を持たない）
COPIES = {
    "architecture": "schemas/design/architecture.schema.yaml",
    "アーキテクチャ図": "schemas/design/architecture.schema.yaml",
    "common": None,
    "共通": None,
    "component": "schemas/design/component.schema.yaml",
    "部品設計": "schemas/design/component.schema.yaml",
    "config": "schemas/design/config.schema.yaml",
    "設定": "schemas/design/config.schema.yaml",
    "dataflow": "schemas/design/dataflow.schema.yaml",
    "データフロー": "schemas/design/dataflow.schema.yaml",
    "dev-command": "schemas/design/dev_command.schema.yaml",
    "開発コマンド": "schemas/design/dev_command.schema.yaml",
    "er": "schemas/design/er.schema.yaml",
    "ER図": "schemas/design/er.schema.yaml",
    "external-api": "schemas/design/external_api.schema.yaml",
    "外部API": "schemas/design/external_api.schema.yaml",
    "index": "schemas/design/index.schema.yaml",
    "interface": "schemas/design/interface.schema.yaml",
    "インターフェース定義": "schemas/design/interface.schema.yaml",
    "library": "schemas/design/library.schema.yaml",
    "外部ライブラリ": "schemas/design/library.schema.yaml",
    "module": "schemas/design/module.schema.yaml",
    "モジュール構成": "schemas/design/module.schema.yaml",
    "nonfunctional": "schemas/design/nonfunctional.schema.yaml",
    "非機能要件": "schemas/design/nonfunctional.schema.yaml",
    "scenario": "schemas/design/scenario.schema.yaml",
    "シナリオ": "schemas/design/scenario.schema.yaml",
    "screen": "schemas/design/screen.schema.yaml",
    "画面設計": "schemas/design/screen.schema.yaml",
    "state-transition": "schemas/design/state_transition.schema.yaml",
    "状態遷移": "schemas/design/state_transition.schema.yaml",
    "test-procedure": "schemas/design/test_procedure.schema.yaml",
    "テスト実行方法": "schemas/design/test_procedure.schema.yaml",
    "layout": "schemas/design/layout.schema.yaml",
    "files": "schemas/knowledge-files.schema.yaml",
    "phase": None,
    "フェーズ": None,
}
# コピーを置くフォルダ（`docs/` へ移したリポジトリと、`dev/` が残るリポジトリ）
COPY_DIRS = ("schemas", "dev/テンプレート")
SCHEMA_LINE = re.compile(r"^(?P<indent>\s*)schema: (?P<path>(?:schemas|dev/テンプレート)/(?P<name>[^/\s]+)\.schema\.yaml)\s*$")


def parse_args(argv):
    """第 1 引数のリポジトリの直下と、第 2 引数の `--dry-run` を返す（不正なら None）。"""
    if not argv or len(argv) > 2 or (len(argv) == 2 and argv[1] != "--dry-run"):
        return None
    root = Path(argv[0])
    if not (root / ".git").exists():
        return None
    return root, len(argv) == 2


def copies(root):
    """リポジトリにある AI Monitor から配ったスキーマのコピーを返す。"""
    found = []
    # フェーズの設計書を持つリポジトリは、フェーズの Schema を残す
    keeps_phase = (root / "docs" / "phase").is_dir() or (root / "dev" / "設計書" / "phase").is_dir()
    for folder in COPY_DIRS:
        for name in COPIES:
            if keeps_phase and name in ("phase", "フェーズ"):
                continue
            path = root / folder / f"{name}.schema.yaml"
            if path.is_file():
                found.append(path)
    return found


def rewrite(text):
    """`dev-docs.yaml` の `schema:` の行のうちコピーを指すものを knowledge の参照に書き換えた本文を返す。"""
    lines = []
    for line in text.splitlines():
        matched = SCHEMA_LINE.match(line)
        target = COPIES.get(matched.group("name")) if matched else None
        if matched and target:
            indent = matched.group("indent")
            lines += [
                f"{indent}schema:",
                f"{indent}  source: {SOURCE}",
                f"{indent}  path: {target}",
                f"{indent}  ref: {REF}",
            ]
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def knowledge_clone():
    """端末の project-index の設定の `sources[]` の knowledge の行の `config` が指すクローンの直下を返す（無ければ None）。"""
    import os
    import subprocess

    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    settings = base / "project-index" / "settings.yaml"
    if not settings.is_file():
        return None
    in_knowledge = False
    for line in settings.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:"):
            in_knowledge = stripped == f"- id: {SOURCE}"
        elif in_knowledge and stripped.startswith("- /"):
            folder = Path(stripped[2:]).parent
            result = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
            return Path(result.stdout.strip()) if result.returncode == 0 else None
    return None


def fail(step, detail=""):
    """失敗の行を出して終える。"""
    print(f"{step}: failed")
    if detail:
        print(detail, file=sys.stderr)
    sys.exit(1)
