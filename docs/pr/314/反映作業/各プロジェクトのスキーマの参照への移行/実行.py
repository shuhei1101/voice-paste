"""配布先の dev-docs.yaml の schema を knowledge の参照に書き換え、AI Monitor から配ったスキーマのコピーを削除する。"""

import difflib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import copies, fail, parse_args, rewrite  # noqa: E402

args = parse_args(sys.argv[1:])
if args is None:
    fail("前提確認", "引数は {配布先のリポジトリの直下} [--dry-run] だけを受け付けます")
root, dry_run = args
config = root / "dev-docs.yaml"
if not config.is_file():
    fail("前提確認", f"{config} がありません")
print("前提確認: ok")

# 計画
text = config.read_text(encoding="utf-8")
new_text = rewrite(text)
targets = copies(root)
if new_text != text:
    sys.stdout.writelines(difflib.unified_diff(text.splitlines(True), new_text.splitlines(True), str(config), str(config)))
for path in targets:
    print(f"削除: {path.relative_to(root)}")
if new_text == text and not targets:
    print("dev-docs.yaml の書き換え: skipped")
    print("コピーの削除: skipped")
    sys.exit(0)
if dry_run:
    print(f"dev-docs.yaml の書き換え: {'changed' if new_text != text else 'skipped'}")
    print(f"コピーの削除: {'changed' if targets else 'skipped'}")
    sys.exit(0)

# 適用（一時ファイル → 検証 → 退避 → 置き換え）
import yaml  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="schema-migration-"))
staged = work / "dev-docs.yaml"
staged.write_text(new_text, encoding="utf-8")
try:
    before = yaml.safe_load(text) or {}
    after = yaml.safe_load(staged.read_text(encoding="utf-8")) or {}
except yaml.YAMLError as e:
    fail("検証", f"書き換えた dev-docs.yaml を YAML として読めません: {e}")
if len(before.get("documents") or []) != len(after.get("documents") or []):
    fail("検証", "書き換えの前後で documents[] の行の数が違います")
print("検証: ok")
backup = work / "backup"
backup.mkdir()
shutil.copy2(config, backup / "dev-docs.yaml")
for path in targets:
    shutil.copy2(path, backup / path.name)
print(f"退避: ok（{backup}）")
if new_text != text:
    shutil.move(str(staged), str(config))
    print("dev-docs.yaml の書き換え: changed")
else:
    print("dev-docs.yaml の書き換え: skipped")
for path in targets:
    path.unlink()
print(f"コピーの削除: {'changed' if targets else 'skipped'}")
