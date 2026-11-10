"""書き換える Issue #258 を gh で読めるかと、Issue を書き換える権限があるかを確かめる（状態は変えない）。"""

import subprocess
import sys

REPO = "shuhei1101/voice-paste"
ISSUE = "258"


def main() -> int:
    # Issue を読めれば ok、読めなければ failed
    result = subprocess.run(["gh", "issue", "view", ISSUE, "--repo", REPO, "--json", "number"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Issue #{ISSUE} の読み取り: failed")
        return 1
    print(f"Issue #{ISSUE} の読み取り: ok")
    # Issue のタイトルと本文を書き換えられる権限（triage 以上）があれば ok
    result = subprocess.run(["gh", "api", f"repos/{REPO}", "--jq", ".permissions.triage"], capture_output=True, text=True)
    if result.returncode != 0 or result.stdout.strip() != "true":
        print("Issue の書き換えの権限: failed")
        return 1
    print("Issue の書き換えの権限: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
