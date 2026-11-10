"""open の Issue（#278 を除く）に旧命名が残っておらず、#258 に「録音セッションの上限」があるかを読むだけで確かめる。"""

import json
import re
import subprocess
import sys

REPO = "shuhei1101/voice-paste"
EXCLUDED = {278}
# 一般の単語のセッション（デスクトップ・OS・ライブラリ）は旧命名に数えない
GENERAL = re.compile(r"(Xorg|Wayland|GNOME|デスクトップ|VAD|ONNX)\s?の\s?セッション|セッションバス|録音セッション")


def main() -> int:
    issues = json.loads(
        subprocess.run(
            ["gh", "issue", "list", "--repo", REPO, "--state", "open", "--limit", "500", "--json", "number,title,body"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    failed = False
    # 1. #278 を除く open の Issue ごとに、旧命名が残っていないかを確かめる
    for issue in issues:
        if issue["number"] in EXCLUDED:
            continue
        text = GENERAL.sub("", f"{issue['title']}\n{issue['body']}")
        if "返送先" in text or "セッション" in text:
            print(f"#{issue['number']} の旧命名: failed")
            failed = True
    if not failed:
        print("open の Issue の旧命名: ok")
    # 2. #258 に新命名が入っているかを確かめる
    target = next((issue for issue in issues if issue["number"] == 258), None)
    if target is None or "録音セッションの上限" not in f"{target['title']}\n{target['body']}":
        print("#258 の録音セッションの上限: failed")
        return 1
    print("#258 の録音セッションの上限: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
