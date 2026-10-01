"""ログのフォルダの JSON Lines を読むテスト用の補助。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_log_records(log_dir: Path, level: str | None = None) -> list[dict[str, Any]]:
    """log_dir の `*.log` の全ての行を JSON として読み、level があればそのレベルの行だけ返す。"""
    records = [
        json.loads(line)
        for log_file in sorted(log_dir.glob("*.log"))
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    if level is None:
        return records
    return [record for record in records if record["level"] == level]
