import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

failed = False
try:
    _, row = common.source_row()
    ok = row["config"] == [common.NEW] and row.get("status") == "serving" and not row.get("errors")
    print(f"project-index の配信元 {common.SOURCE_ID}: {'ok' if ok else 'failed'}")
    print(f"  config={row['config']} status={row.get('status')} errors={row.get('errors')}")
    failed |= not ok
except Exception as e:
    print(f"project-index の配信元 {common.SOURCE_ID}: failed")
    print(str(e), file=sys.stderr)
    failed = True
for label, path in common.TEXT_SETTINGS.items():
    with open(path, encoding="utf-8") as f:
        text = f.read()
    ok = common.OLD not in text and common.NEW in text
    print(f"{label}: {'ok' if ok else 'failed'}")
    failed |= not ok
sys.exit(1 if failed else 0)
