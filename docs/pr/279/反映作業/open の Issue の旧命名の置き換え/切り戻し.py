"""実行で退避した #258 のタイトルと本文へ書き戻す。"""

import json
import subprocess
import sys
from pathlib import Path

REPO = "shuhei1101/voice-paste"
ISSUE = "258"
BACKUP = Path.home() / ".local/state/voice-paste/pr-279/issue-258.json"


def main() -> int:
    # 退避したファイルが無ければ戻せない
    if not BACKUP.is_file():
        print("退避したファイル: failed")
        return 1
    saved = json.loads(BACKUP.read_text(encoding="utf-8"))
    subprocess.run(
        ["gh", "issue", "edit", ISSUE, "--repo", REPO, "--title", saved["title"], "--body", saved["body"]],
        check=True,
        capture_output=True,
        text=True,
    )
    print("Issue の書き戻し: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
