import difflib
import os
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common

dry_run = common.check_args()

# 前提確認
try:
    version, row = common.source_row()
except Exception as e:
    print("前提確認: failed")
    print(str(e), file=sys.stderr)
    sys.exit(1)
for path in common.TEXT_SETTINGS.values():
    if not os.path.isfile(path):
        print("前提確認: failed")
        print(f"ファイルがありません: {path}", file=sys.stderr)
        sys.exit(1)
if os.path.isfile(common.NEW):
    print("develop の worktree の project-index.yaml: ok")
elif dry_run:
    print("develop の worktree の project-index.yaml: missing")
else:
    print("前提確認: failed")
    print(f"ファイルがありません（マージが develop の worktree に入っていない）: {common.NEW}", file=sys.stderr)
    sys.exit(1)
print("前提確認: ok")

# 計画
config = row["config"]
new_config = [common.NEW if c == common.OLD else c for c in config]
pi_changed = new_config != config
if pi_changed:
    print(f"--- {common.PROJECT_INDEX_SETTINGS} (sources[id={common.SOURCE_ID}].config)")
    print(f"+++ {common.PROJECT_INDEX_SETTINGS} (sources[id={common.SOURCE_ID}].config)")
    print(f"-{config}")
    print(f"+{new_config}")
text_plans = {}
for label, path in common.TEXT_SETTINGS.items():
    with open(path, encoding="utf-8") as f:
        old_text = f.read()
    count = old_text.count(common.OLD)
    if count > 1:
        print(f"{label}: failed")
        print(f"{path} に {common.OLD} が {count} か所あります（想定は 1 か所以下）", file=sys.stderr)
        sys.exit(1)
    new_text = old_text.replace(common.OLD, common.NEW)
    text_plans[label] = (path, old_text, new_text)
    if new_text != old_text:
        sys.stdout.writelines(difflib.unified_diff(
            old_text.splitlines(True), new_text.splitlines(True), fromfile=path, tofile=path))

if dry_run:
    print(f"project-index の端末の設定の書き換え: {'changed' if pi_changed else 'skipped'}")
    for label, (_, old_text, new_text) in text_plans.items():
        print(f"{label}の書き換え: {'changed' if new_text != old_text else 'skipped'}")
    sys.exit(0)

# 適用
failed = False
if pi_changed:
    status, body = common.patch_config(version, new_config)
    if status == 200:
        print("project-index の端末の設定の書き換え: changed")
    else:
        print("project-index の端末の設定の書き換え: failed")
        print(f"PATCH {common.API}/settings/sources/{common.SOURCE_ID}: HTTP {status} {body}", file=sys.stderr)
        failed = True
else:
    print("project-index の端末の設定の書き換え: skipped")
for label, (path, old_text, new_text) in text_plans.items():
    if new_text == old_text:
        print(f"{label}の書き換え: skipped")
        continue
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new_text)
    with open(tmp, encoding="utf-8") as f:
        written = f.read()
    if common.OLD in written or common.NEW not in written:
        os.remove(tmp)
        print(f"{label}の検証: failed")
        failed = True
        continue
    print(f"{label}のバックアップ: {common.backup(path)}")
    shutil_mode = os.stat(path).st_mode
    os.chmod(tmp, shutil_mode)
    os.replace(tmp, path)
    print(f"{label}の書き換え: changed")
sys.exit(1 if failed else 0)
