"""実行で退避した mdmark.config.yaml を書き戻す（実行で作った場合は消す）。"""

from __future__ import annotations

import os
import sys

from common import TARGET, fail, repo_from_args

repo, _ = repo_from_args(sys.argv, allow_dry_run=False)
backup = repo / f"{TARGET}.bak"
created = repo / f"{TARGET}.created"
# 退避した元のファイルがある: 書き戻す
if backup.exists():
    os.replace(backup, repo / TARGET)
    print(f"{TARGET} の書き戻し: changed")
# 実行で作った: 消す
elif created.exists():
    (repo / TARGET).unlink(missing_ok=True)
    created.unlink()
    print(f"{TARGET} の削除: changed")
else:
    fail("退避したファイル", f"{backup} も {created} もありません")
