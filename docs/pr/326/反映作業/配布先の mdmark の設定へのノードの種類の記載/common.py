"""配布先の mdmark の設定へのノードの種類の記載で、3 つのスクリプトが共有する固定値と読み書き。"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

# 対象のファイル（対象のリポジトリの直下からのパス）
TARGET = "mdmark.config.yaml"
# AI Monitor の design_docs が生成する図のノードの種類（AI Monitor の mdmark.config.yaml の map.kinds と同じ値）
KINDS = {
    "external": {"label": "外部", "icon": "globe", "shape": "pill", "color": "green"},
    "script": {"label": "処理", "icon": "cog", "shape": "rounded"},
    "data": {"label": "保存先", "icon": "database", "shape": "rect", "color": "purple"},
    "start": {"label": "開始", "icon": "play", "shape": "pill", "color": "blue"},
    "question": {"label": "質問", "icon": "circle-help", "shape": "double", "color": "orange"},
    "action": {"label": "アクション", "icon": "square-pen", "shape": "rounded"},
    "result": {"label": "結果", "icon": "flag", "shape": "pill", "color": "green"},
}
# 線の種類（AI Monitor の mdmark.config.yaml の map.lines と同じ値）
LINES = {
    "-.->": {"dash": "dashed", "head": "open"},
    "==>": {"width": "thick"},
}


def fail(step: str, detail: str = "") -> None:
    """手順の失敗を出して終える。"""
    print(f"{step}: failed")
    if detail:
        print(detail)
    sys.exit(1)


def repo_from_args(argv: list[str], *, allow_dry_run: bool) -> tuple[Path, bool]:
    """第 1 引数の対象のリポジトリと、`--dry-run` を受け取る（それ以外の引数は前提確認で失敗にする）。"""
    args = argv[1:]
    dry_run = False
    if allow_dry_run and len(args) == 2 and args[1] == "--dry-run":
        dry_run = True
        args = args[:1]
    if len(args) != 1:
        fail("前提確認", f"引数: {argv[1:]}")
    repo = Path(args[0]).resolve()
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or Path(result.stdout.strip()).resolve() != repo:
        fail("前提確認", f"git -C {repo} rev-parse --show-toplevel\n{result.stderr}")
    return repo, dry_run


def yaml_rt() -> YAML:
    """コメントとほかのキーを保って読み書きする YAML。"""
    rt = YAML()
    rt.preserve_quotes = True
    rt.width = 4096
    rt.indent(mapping=2, sequence=4, offset=2)
    return rt


def dump(rt: YAML, doc: object) -> str:
    """YAML を文字列にする。"""
    buf = io.StringIO()
    rt.dump(doc, buf)
    return buf.getvalue()


def missing_kinds(doc: object) -> list[str]:
    """設定の map.kinds・map.lines のうち、AI Monitor の値と違う・無いものの名前を返す。"""
    mapping = doc.get("map") if isinstance(doc, dict) else None
    kinds = mapping.get("kinds") if isinstance(mapping, dict) else None
    lines = mapping.get("lines") if isinstance(mapping, dict) else None
    names = [name for name, value in KINDS.items() if not isinstance(kinds, dict) or kinds.get(name) != value]
    names += [name for name, value in LINES.items() if not isinstance(lines, dict) or lines.get(name) != value]
    return names
