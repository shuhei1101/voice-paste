import os
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

failed = False
version, row = common.source_row()
config = [common.OLD if c == common.NEW else c for c in row["config"]]
if config == row["config"]:
    print("project-index の端末の設定の書き戻し: skipped")
else:
    status, body = common.patch_config(version, config)
    print(f"project-index の端末の設定の書き戻し: {'changed' if status == 200 else 'failed'}")
    if status != 200:
        print(f"HTTP {status} {body}", file=sys.stderr)
        failed = True
for label, path in common.TEXT_SETTINGS.items():
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if common.NEW not in text:
        print(f"{label}の書き戻し: skipped")
        continue
    print(f"{label}のバックアップ: {common.backup(path)}")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text.replace(common.NEW, common.OLD))
    os.chmod(tmp, os.stat(path).st_mode)
    os.replace(tmp, path)
    print(f"{label}の書き戻し: changed")
sys.exit(1 if failed else 0)
