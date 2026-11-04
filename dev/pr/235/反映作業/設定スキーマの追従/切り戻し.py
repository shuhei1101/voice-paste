"""実行で退避した settings.yaml のバックアップから元の中身へ戻す。"""

import shutil
import sys
from pathlib import Path

TARGET = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml")
BACKUP = Path("/home/shuhei2441/.config/ai-monitor/settings.yaml.bak-pr235")


def main() -> int:
    """バックアップがあれば書き戻す。"""
    if not BACKUP.is_file():
        print("退避したファイル: failed")
        return 1
    shutil.copy2(BACKUP, TARGET)
    print("設定の書き戻し: changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
