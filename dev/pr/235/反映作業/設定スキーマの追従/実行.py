"""AI Monitor の settings.yaml に my_plugins_repo を追加し、voice-input の rule_indexes から実在しない索引を外す。"""

import difflib
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

TARGET = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml")
BACKUP = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml.bak-pr235")
PROJECT_NAME = "voice-input"
MY_PLUGINS_REPO = "shuhei1101/my-plugins"
MY_PLUGINS_BLOCK = [
    "# 言語・フレームワークの規約を持つリポジトリ（ルール改修 Issue の起票先）\n",
    f"my_plugins_repo: {MY_PLUGINS_REPO}\n",
    "\n",
]
MISSING_INDEX = "/mnt/c/Users/shuhe/repo/voice-paste/rules.yaml"
KEPT_INDEX = "/mnt/c/Users/shuhe/repo/voice-paste/docs/rules.yaml"
MISSING_INDEX_LINE = f"    - {MISSING_INDEX}\n"


def project_block(lines: list[str]) -> tuple[int, int]:
    """voice-input の行の開始と終了（次の `- name:` の手前）の行番号を返す。"""
    start = lines.index(f"- name: {PROJECT_NAME}\n")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("- name: ")),
        len(lines),
    )
    return start, end


def plan(lines: list[str]) -> tuple[list[str], list[str]]:
    """あるべき中身の行と、手順ごとの結果の行を返す。"""
    new = list(lines)
    results = []
    data = yaml.safe_load("".join(lines))
    # my_plugins_repo が既にあるか
    if data.get("my_plugins_repo") == MY_PLUGINS_REPO:
        # ある: 何もしない
        results.append("my_plugins_repo の追加: skipped")
    else:
        # 無い: projects: と、その直前のコメントの行の手前に置く
        position = new.index("projects:\n")
        while position > 0 and new[position - 1].startswith("#"):
            position -= 1
        new[position:position] = MY_PLUGINS_BLOCK
        results.append("my_plugins_repo の追加: changed")
    # voice-input の rule_indexes に実在しない索引の行が残っているか
    start, end = project_block(new)
    if MISSING_INDEX_LINE in new[start:end]:
        # 残っている: その行だけを外す
        new.pop(new.index(MISSING_INDEX_LINE, start, end))
        results.append("rule_indexes の整理: changed")
    else:
        # 外れている: 何もしない
        results.append("rule_indexes の整理: skipped")
    return new, results


def verify(text: str) -> bool:
    """書き換えた中身が YAML として読め、あるべき値を持つかを返す。"""
    data = yaml.safe_load(text)
    project = next(p for p in data["projects"] if p.get("name") == PROJECT_NAME)
    return (
        data.get("my_plugins_repo") == MY_PLUGINS_REPO
        and project.get("rule_indexes") == [KEPT_INDEX]
    )


def main() -> int:
    """前提確認 → 計画 → 適用の順に進め、--dry-run なら計画で止める。"""
    dry_run = sys.argv[1:] == ["--dry-run"]
    # 1. 前提確認（設定があり、残す索引が実在し、外す索引が実在しない）
    if not TARGET.is_file() or not Path(KEPT_INDEX).is_file() or Path(MISSING_INDEX).exists():
        print("前提確認: failed")
        return 1
    lines = TARGET.read_text(encoding="utf-8").splitlines(keepends=True)
    if "projects:\n" not in lines or f"- name: {PROJECT_NAME}\n" not in lines:
        print("前提確認: failed")
        return 1
    print("前提確認: ok")
    # 2. 計画（--dry-run もここを通る）
    new, results = plan(lines)
    # 既にあるべき状態か
    if new == lines:
        for line in results:
            print(line)
        return 0
    sys.stdout.writelines(difflib.unified_diff(lines, new, str(TARGET), str(TARGET)))
    # dry-run なら計画で止める
    if dry_run:
        for line in results:
            print(line)
        return 0
    # 3. 適用（検証 → 退避 → 置き換え）
    text = "".join(new)
    if not verify(text):
        print("検証: failed")
        return 1
    print("検証: ok")
    shutil.copy2(TARGET, BACKUP)
    print(f"退避: ok（{BACKUP}）")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=TARGET.parent, delete=False) as f:
        f.write(text)
    Path(f.name).replace(TARGET)
    for line in results:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
