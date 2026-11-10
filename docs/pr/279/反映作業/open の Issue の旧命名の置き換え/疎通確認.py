"""書き換える Issue #258 を gh で読めるかを確かめる（状態は変えない）。"""

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
