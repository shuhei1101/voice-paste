"""設計書の新しいスキーマへの変換の共通の定義。"""

import os
import re
import subprocess
import sys
from pathlib import Path

# 変換を掛ける AI Monitor の作業ツリーと、統一する knowledge のスキーマのリビジョン
AI_MONITOR = Path("/mnt/c/Users/shuhe/repo/ai-monitor/.claude/worktrees/develop")
KNOWLEDGE = Path("/mnt/c/Users/shuhe/repo/knowledge")
FROM_VERSION = "v0.4.0"
TO_REF = "design-schemas/v8.3.0"
BACKUP_NAME = "ai-monitor-pr314-backup"

DEV_DOCS = Path("dev-docs.yaml")
# knowledge に無く、プロジェクトが持ち続けるスキーマ
LOCAL_SCHEMAS = ("glossary.schema.yaml",)
DOCS_DIR = Path("docs")
# 実装の場所の接頭辞 → その場所のコードの行を持つ管理用の YAML
FILES_YMLS = {
    "src/": Path("src/files.yml"),
    "haas_server/src/": Path("haas_server/src/files.yml"),
}
# 一時フォルダへ写さないもの（変換と検査が読まないもの）
COPY_IGNORE = (".git", "node_modules", ".venv", ".claude", "__pycache__")

# knowledge のスキーマの行の ref
REF_LINE = re.compile(r"^(?P<head>\s*ref:\s*)(?P<ref>design-schemas/v[0-9.]+)\s*$")
# 書き換えるキー（knowledge のスキーマが持たないキー）
KEYS = ("implementation", "introduced", "error_message", "directory", "per_env")
# 書き換える違反の行（{ファイル}:{項目のパス}.{キー}: Schema に無い項目。最上位のキーは項目のパスを持たない）
VIOLATION = re.compile(rf"^(?P<file>[^:]+):(?:(?P<path>.+)\.)?(?P<key>{'|'.join(KEYS)}): Schema に無い項目$")
# 検査は 1 つの要素につき違反を 1 件ずつ出すため、キーの数と、違反が無いことを確かめる 1 回だけ繰り返す
MAX_ROUNDS = len(KEYS) + 1
# モジュール構成の directory のツリーでない記述と、上書きを持たない per_env を移す notes の節
DIRECTORY_NOTE = "ディレクトリ構成"
PER_ENV_NOTE = "環境ごとの値"
# モジュール構成の directory のツリーを移すフォルダ構成の設計書と、ツリーを読む配布元の変換
LAYOUT_GLOB = "docs/layout/LAY-*.yaml"
UPSTREAM_CONVERSION = f"{FROM_VERSION}:schemas/conversions/{FROM_VERSION}.py"
# config の per_env を overrides の行にする元（OS ごとの上書き）
OS_OVERRIDES_FILE = Path("config/defaults.yaml")
OS_OVERRIDES_KEY = "os_overrides"

# 書き換えの後も残ってよい違反（対応テストファイルの不在と、データの設計書の作成が直す source の欠落）
ALLOWED = (
    re.compile(r"^[^:]+:test_file: 対応テストファイルがありません: "),
    re.compile(r"^docs/er/[^:]+:tables\[.*\]\.source: 必須の項目が無い$"),
)
# 要素を値で指すときのキー
ELEMENT_KEYS = ("name", "key", "id", "scope")


def fail(step, command=None, stderr=None):
    """失敗した手順を出して終える。"""
    print(f"{step}: failed")
    if command:
        print(f"$ {' '.join(str(c) for c in command)}")
    if stderr:
        print(stderr.rstrip())
    sys.exit(1)


def parse_args(argv):
    """引数が無ければ False、`--dry-run` だけなら True、それ以外は None を返す。"""
    if not argv:
        return False
    if argv == ["--dry-run"]:
        return True
    return None


def design_docs(command, root):
    """AI Monitor の設計書のコマンドを流し、終了コード・標準出力・標準エラー・コマンドを返す。"""
    args = ["uv", "run", "python", "-B", "-m", "ai_monitor.design_docs", *command, "--root", str(root)]
    env = {**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(args, cwd=AI_MONITOR, env=env, capture_output=True, text=True, check=False)
    return done.returncode, done.stdout, done.stderr, args


def validate_lines(root):
    """設計書の検査を流し、違反の行の並びを返す。"""
    _, stdout, stderr, _ = design_docs(["validate"], root)
    return [line for line in (stdout + stderr).splitlines() if line.strip()]


def unexpected(lines):
    """残ってよい違反以外の行を返す。"""
    return [line for line in lines if not any(p.match(line) for p in ALLOWED)]


def knowledge_refs(text):
    """dev-docs.yaml の knowledge のスキーマの行の ref を並べて返す。"""
    return [m.group("ref") for line in text.splitlines() if (m := REF_LINE.match(line))]


def git_dir(root):
    """リポジトリの git のディレクトリ（worktree なら .git/worktrees/{名前}）を返す。"""
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--absolute-git-dir"], capture_output=True, text=True, check=True
    )
    return Path(done.stdout.strip())
