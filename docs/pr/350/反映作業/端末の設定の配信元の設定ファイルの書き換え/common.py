import sys

sys.dont_write_bytecode = True

import json
import os
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime

SOURCE_ID = "voice-input"
OLD = "/home/shuhei2441/repo/voice-paste/.claude/worktrees/develop/dev-docs.yaml"
NEW = "/home/shuhei2441/repo/voice-paste/.claude/worktrees/develop/project-index.yaml"
API = "http://127.0.0.1:8786"
PROJECT_INDEX_SETTINGS = os.path.expanduser("~/.config/project-index/settings.yaml")
TEXT_SETTINGS = {
    "dev-docs の端末の設定": os.path.expanduser("~/.config/dev-docs/settings.yaml"),
    "alias-inject の端末の設定": os.path.expanduser("~/.config/alias-inject/settings.yaml"),
}
RETRY = 3
RETRY_INTERVAL = 2


def request(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    last = None
    for _ in range(RETRY):
        req = urllib.request.Request(API + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, json.loads(e.read() or b"null")
            last = f"HTTP {e.code}: {e.read()[:300]!r}"
        except (urllib.error.URLError, TimeoutError) as e:
            last = repr(e)
        time.sleep(RETRY_INTERVAL)
    raise RuntimeError(f"{method} {API}{path} が {RETRY} 回失敗しました: {last}")


def source_row():
    status, body = request("GET", "/settings/sources")
    if status != 200:
        raise RuntimeError(f"GET /settings/sources: HTTP {status} {body}")
    rows = [r for r in body["sources"] if r.get("id") == SOURCE_ID]
    if len(rows) != 1:
        raise RuntimeError(f"配信元 {SOURCE_ID} の行が {len(rows)} 件あります")
    return body["version"], rows[0]


def patch_config(version, config):
    return request("PATCH", f"/settings/sources/{SOURCE_ID}", {"config": config, "expectedVersion": version})


def backup(path):
    dst = f"{path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, dst)
    return dst


def check_args():
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] != "--dry-run"):
        print("前提確認: failed")
        print(f"受け付けない引数: {sys.argv[1:]}", file=sys.stderr)
        sys.exit(1)
    return len(sys.argv) == 2
