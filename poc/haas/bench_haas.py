"""Windows から wsl.exe で検証のサーバーを起動し、検証の音声を HTTP で送信して結果を JSON に書く。

Windows の Python で動かす: `python bench_haas.py {音声のフォルダ} {結果の JSON}`
"""

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:18990"
# WSL の中から見た起動スクリプトの場所
SERVER_SCRIPT = "/mnt/c/Users/shuhe/repo/voice-paste/.claude/worktrees/poc-transcription-haas-wsl/poc/haas/start_server.sh"
STARTUP_TIMEOUT_SEC = 600
REPEATS = 3
VOCABS = ["none", "v1", "v2"]


def _start_server() -> tuple[subprocess.Popen[bytes], float, dict[str, object]]:
    """wsl.exe でサーバーを起動し、/health が返るまでの秒数を測る。"""
    begin = time.perf_counter()
    process = subprocess.Popen(["wsl.exe", "-e", "bash", SERVER_SCRIPT])
    while True:
        # 起動の上限を過ぎたか
        if time.perf_counter() - begin > STARTUP_TIMEOUT_SEC:
            process.terminate()
            raise TimeoutError("サーバーが起動の上限までに応答しなかった")
        try:
            health = httpx.get(f"{BASE_URL}/health", timeout=2).json()
            return process, time.perf_counter() - begin, health
        except httpx.TransportError:
            # まだ待ち受けていない: 少し待って問い合わせ直す
            time.sleep(0.5)


def _post(client: httpx.Client, wav: Path, vocab: str, longform_mode: str) -> tuple[float, dict[str, object]]:
    """1 件を送信し、HTTP の往復を含む秒数と応答を返す。"""
    begin = time.perf_counter()
    response = client.post(
        f"{BASE_URL}/transcribe",
        files={"audio": (wav.name, wav.read_bytes(), "audio/wav")},
        data={"vocab": vocab, "longform_mode": longform_mode},
    )
    elapsed = time.perf_counter() - begin
    response.raise_for_status()
    return elapsed, response.json()


def main(audio_dir: Path, out_path: Path) -> None:
    """起動の時間・長さと Vocabulary ごとの結果を測って書く。"""
    manifest = json.loads((audio_dir / "manifest.json").read_text(encoding="utf-8"))
    process, startup_sec, health = _start_server()
    results: dict[str, object] = {"startup_sec": round(startup_sec, 2), "health": health, "runs": []}
    try:
        with httpx.Client(timeout=300) as client:
            # 1. 最初の 1 件（初回の CUDA の準備を含む）の時間を別に控える
            first_sec, _ = _post(client, audio_dir / manifest[0]["file"], "v2", "batch")
            results["first_request_sec"] = round(first_sec, 3)
            # 2. 音声ごと・Vocabulary ごとに REPEATS 回送信し、中央値を控える
            for item in manifest:
                modes = ["batch", "sequential"] if item["length_class"] == "long" else ["batch"]
                for vocab in VOCABS:
                    for mode in modes:
                        times, responses = [], []
                        for _ in range(REPEATS):
                            elapsed, body = _post(client, audio_dir / item["file"], vocab, mode)
                            times.append(elapsed)
                            responses.append(body)
                        last = responses[-1]
                        results["runs"].append(
                            {
                                "id": item["id"],
                                "vocab": vocab,
                                "longform_mode": mode,
                                "status": 200,
                                "roundtrip_sec": round(statistics.median(times), 3),
                                "server_sec": round(statistics.median(r["transcribe_sec"] for r in responses), 3),
                                "chunk_count": last["chunk_count"],
                                "text": last["text"],
                                "max_allocated_mb": last["max_allocated_mb"],
                                "reserved_mb": last["reserved_mb"],
                            }
                        )
                        print(item["id"], vocab, mode, results["runs"][-1]["roundtrip_sec"], last["text"][:40])
    finally:
        process.terminate()
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
