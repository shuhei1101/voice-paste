"""dev-docs.yaml の ref と、設計書の検査で残る違反を読み取りだけで確かめる。"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DEV_DOCS, TO_REF, fail, knowledge_refs, unexpected, validate_lines  # noqa: E402

ROOT = Path.cwd()

refs = knowledge_refs((ROOT / DEV_DOCS).read_text(encoding="utf-8"))
others = sorted({ref for ref in refs if ref != TO_REF})
if not refs or others:
    print(f"観測した ref: {sorted(set(refs))}")
    fail("dev-docs.yaml の ref")
print(f"dev-docs.yaml の ref: ok（{len(refs)} 行が {TO_REF}）")

rest = unexpected(validate_lines(ROOT))
if rest:
    fail("設計書の検査", stderr="\n".join(rest))
print("設計書の検査: ok（残る違反は対応テストファイルの不在と tables[].source の欠落だけ）")
