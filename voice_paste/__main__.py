"""python -m voice_paste のエントリーポイント。"""

import os
import sys
from pathlib import Path


def _register_bundled_cuda_dlls() -> None:
    """PyInstaller bundle 時に nvidia-* の DLL ディレクトリを検索パスへ登録する。"""
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # デバッグ用: DLL登録状況をファイルに記録
    debug_log = Path(sys.executable).parent / "log" / "dll_debug.log"
    debug_log.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"frozen={getattr(sys, 'frozen', False)}", f"_MEIPASS={base}"]
    candidates = [
        base / "nvidia" / "cublas" / "bin",
        base / "nvidia" / "cudnn" / "bin",
        base / "nvidia" / "cuda_nvrtc" / "bin",
        base / "ctranslate2",
    ]
    for dll_dir in candidates:
        exists = dll_dir.is_dir()
        lines.append(f"{dll_dir} exists={exists}")
        if exists:
            try:
                os.add_dll_directory(str(dll_dir))
                lines.append(f"  -> registered OK")
            except (OSError, AttributeError) as e:
                lines.append(f"  -> FAILED: {e}")
    # PATH にも追加（os.add_dll_directory だけでは不十分な場合の保険）
    path_additions = [str(d) for d in candidates if d.is_dir()]
    if path_additions:
        os.environ["PATH"] = ";".join(path_additions) + ";" + os.environ.get("PATH", "")
        lines.append(f"PATH prepended: {';'.join(path_additions)}")
    debug_log.write_text("\n".join(lines), encoding="utf-8")


_register_bundled_cuda_dlls()

from voice_paste.main import run

if __name__ == "__main__":
    run()
