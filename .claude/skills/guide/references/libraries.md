# 外部ライブラリ

定義ファイル: `pyproject.toml`

| ライブラリ | バージョン | 用途 | 関連ファイル |
|-----------|-----------|------|-------------|
| `faster-whisper` | ~=1.0 | 音声文字起こしエンジン | `transcription/whisper_transcriber.py` |
| `sounddevice` | ~=0.5 | マイク音声入力 | `audio/recorder.py` |
| `scipy` | ~=1.13 | WAVファイル読み書き | `audio/recorder.py` |
| `pyperclip` | ~=1.9 | クリップボード操作 | `input/keyboard_sender.py` |
| `pynput` | ~=1.7 | グローバルホットキー・仮想キーボード | `main.py`, `gui.py`, `settings_gui.py`, `input/keyboard_sender.py` |
| `python-dotenv` | ~=1.0 | .env読み込み | `config.py`, `settings_gui.py` |
| `pystray` | ~=0.19 | システムトレイアイコン | `tray.py` |
| `Pillow` | >=11.0 | トレイアイコン画像処理 | `tray.py` |
| `nvidia-cublas-cu12` | — | CUDA線形代数（GPU高速化） | ランタイム依存 |
| `nvidia-cudnn-cu12` | >=9,<10 | CUDA DNN（GPU推論） | ランタイム依存 |

## ライブラリ更新・追加

- **バージョン更新**: `pyproject.toml` の依存バージョンを変更 → `pip install -e .`
- **新規追加**: `pyproject.toml` の `dependencies` に追加
