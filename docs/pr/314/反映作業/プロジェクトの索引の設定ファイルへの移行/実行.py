"""配布先の .claude/settings.json の RULE_INJECT_INDEXES_PROJECT を rule-inject の設定ファイルの projects[] へ移す。

引数: {対象のリポジトリの場所} [--dry-run]
"""

import difflib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENV_KEY = "RULE_INJECT_INDEXES_PROJECT"
# 値の説明を置く慣習のキー（同じく取り除く）
NOTE_KEY = "_RULE_INJECT_INDEXES_PROJECT"
SETTINGS_JSON = Path(".claude/settings.json")
RULE_INJECT_SETTINGS = Path("~/.config/rule-inject/settings.yaml").expanduser()
BACKUP_SUFFIX = ".bak-ai-monitor-3211"
COMMIT_SUBJECT = (
    f"{ENV_KEY} を rule-inject の設定ファイルの projects へ移す（shuhei1101/ai-monitor#3040）"
)


def quote(value: str) -> str:
    """rule-inject の設定ファイルの読み取りが受け付ける単一引用符の文字列にする。"""
    return "'" + value.replace("'", "''") + "'"


def show_diff(path: Path, old: str, new: str) -> None:
    """変わる内容を差分で出す。"""
    sys.stdout.writelines(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), str(path), str(path)
        )
    )


def write_atomic(path: Path, text: str) -> None:
    """同じフォルダの一時ファイルへ書いてから置き換える。"""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
    Path(handle.name).replace(path)


def clone_root(repo: Path) -> Path:
    """worktree を含め、クローン本体の直下を返す（rule-inject は worktree を本体のパスで当てる）。"""
    common_dir = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(common_dir).parent


def plan_yaml(original: str, clone: Path, indexes: list[str]) -> str:
    """projects の要素を 1 つ足した設定ファイルの本文を返す。"""
    element = [
        f"  - match: {quote(str(clone))}",
        "    indexes:",
        *(f"      - {quote(i)}" for i in indexes),
    ]
    # projects が既にあれば末尾へ要素を足し、無ければ projects ごと足す
    if "\nprojects:" in "\n" + original:
        return original.rstrip("\n") + "\n" + "\n".join(element) + "\n"
    return original.rstrip("\n") + "\nprojects:\n" + "\n".join(element) + "\n"


def projects_is_last(original: str) -> bool:
    """最上位のキーの並びで、projects の後ろに別のキーが無いかを返す。"""
    top_keys = [
        line.split(":", 1)[0] for line in original.splitlines() if line[:1] not in ("", " ", "#")
    ]
    return "projects" not in top_keys or top_keys[-1] == "projects"


def remove_env_lines(original: str, keys: tuple[str, ...]) -> str:
    """env のキーの行だけを消し、残りの行（空行・並び）はそのまま残す。"""
    lines = original.splitlines(keepends=True)
    kept: list[str] = []
    skip_blank = False
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(f'"{key}":') for key in keys):
            # キーの行を消し、続く空行も 1 行だけ消す（キーの塊の区切りを残さない）
            skip_blank = True
            continue
        if skip_blank and not stripped:
            skip_blank = False
            continue
        skip_blank = False
        kept.append(line)
    text = "".join(kept)
    # 消した行がオブジェクトの最後だった場合、直前の行の末尾のカンマを外す
    fixed: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.strip().startswith("}") and fixed and lines != text.splitlines(keepends=True):
            # 消した行の後ろに残った、閉じ括弧の直前の空行を除く
            while fixed and not fixed[-1].strip():
                fixed.pop()
            index = len(fixed) - 1
            if index >= 0 and fixed[index].rstrip().endswith(","):
                fixed[index] = fixed[index].rstrip()[:-1] + "\n"
        fixed.append(line)
    return "".join(fixed)


def main() -> int:
    """前提確認 → 計画 → 適用の順に移す。"""
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[1:]
    # 前提確認: 対象のリポジトリと、rule-inject の利用者の設定ファイルへの移行（rule-inject の反映作業）の後であること
    if len(args) != 1 or not (Path(args[0]) / ".git").exists():
        print("前提確認: failed（リポジトリの場所を第 1 引数で渡す）")
        return 1
    if not RULE_INJECT_SETTINGS.is_file():
        print(
            f"前提確認: failed（{RULE_INJECT_SETTINGS} が無い。rule-inject の反映作業の後に実行する）"
        )
        return 1
    repo = Path(args[0]).resolve()
    clone = clone_root(repo)
    settings_json = repo / SETTINGS_JSON
    print("前提確認: ok")
    # 計画: env に旧い環境変数が無ければ何もしない
    original_json = settings_json.read_text(encoding="utf-8") if settings_json.exists() else ""
    data = json.loads(original_json) if original_json else {}
    env = data.get("env", {})
    if ENV_KEY not in env:
        print("移行: skipped")
        return 0
    indexes = [index for index in env[ENV_KEY].split(",") if index]
    original_yaml = RULE_INJECT_SETTINGS.read_text(encoding="utf-8")
    # クローン本体の直下の rules.yaml だけなら、rule-inject の既定で読まれるため projects に足さない
    default_only = indexes == [str(clone / "rules.yaml")]
    if default_only:
        new_yaml = original_yaml
    elif f"match: {quote(str(clone))}" in original_yaml or f"match: {clone}\n" in original_yaml:
        print(
            "rule-inject の設定ファイルの projects: failed（同じ match の要素が既にある。手で統合する）"
        )
        return 1
    elif not projects_is_last(original_yaml):
        print(
            "rule-inject の設定ファイルの projects: failed（projects の後ろに別の最上位のキーがある。手で統合する）"
        )
        return 1
    else:
        new_yaml = plan_yaml(original_yaml, clone, indexes)
    # .claude/settings.json は 2 つのキーの行だけを消し、他の行の書き方を残す
    new_json = remove_env_lines(original_json, (ENV_KEY, NOTE_KEY))
    del env[ENV_KEY]
    env.pop(NOTE_KEY, None)
    try:
        parsed = json.loads(new_json)
    except json.JSONDecodeError:
        parsed = None
    if parsed != data:
        print(f"{SETTINGS_JSON} の env: failed（行だけを消すと JSON として読めない。手で消す）")
        return 1
    if new_yaml != original_yaml:
        show_diff(RULE_INJECT_SETTINGS, original_yaml, new_yaml)
    show_diff(settings_json, original_json, new_json)
    projects_result = "skipped（直下の rules.yaml は既定で読まれる）" if default_only else "changed"
    if dry_run:
        print(f"rule-inject の設定ファイルの projects: {projects_result}")
        print(f"{SETTINGS_JSON} の env: changed")
        print("commit: changed")
        return 0
    # 適用: 退避 → 置き換え → commit
    if not default_only:
        shutil.copy2(
            RULE_INJECT_SETTINGS,
            RULE_INJECT_SETTINGS.with_name(RULE_INJECT_SETTINGS.name + BACKUP_SUFFIX),
        )
        write_atomic(RULE_INJECT_SETTINGS, new_yaml)
    print(f"rule-inject の設定ファイルの projects: {projects_result}")
    write_atomic(settings_json, new_json)
    print(f"{SETTINGS_JSON} の env: changed")
    subprocess.run(["git", "-C", str(repo), "add", str(SETTINGS_JSON)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", COMMIT_SUBJECT], check=True, capture_output=True
    )
    print("commit: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
