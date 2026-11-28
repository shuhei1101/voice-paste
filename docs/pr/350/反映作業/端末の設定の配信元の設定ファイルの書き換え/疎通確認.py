import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

failed = False
try:
    common.source_row()
    print("project-index の端末の設定の API: ok")
except Exception as e:
    print("project-index の端末の設定の API: failed")
    print(f"GET {common.API}/settings/sources: {e}", file=sys.stderr)
    failed = True
for label, path in [("project-index の端末の設定", common.PROJECT_INDEX_SETTINGS), *common.TEXT_SETTINGS.items()]:
    if os.path.isfile(path) and os.access(path, os.R_OK):
        print(f"{label}: ok")
    else:
        print(f"{label}: failed")
        print(f"読み取れません: {path}", file=sys.stderr)
        failed = True
sys.exit(1 if failed else 0)
