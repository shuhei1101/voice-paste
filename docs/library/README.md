# library

採用済みの外部ライブラリ / 外部ツールのリファレンス

## 目次

<!-- table: data -->

| ページ | 概要 |
| --- | --- |
| [faster-whisper](./LIB-8.yaml) | ローカルの Whisper で音声を文字に起こす |
| [sounddevice](./LIB-27.yaml) | マイクの入力を開いて録音する |
| [scipy](./LIB-26.yaml) | 録音を WAV に読み書きする |
| [numpy](./LIB-11.yaml) | 録音した音を配列で貯め、音量を求める |
| [pyperclip](./LIB-20.yaml) | 起こした文字をクリップボードへ書く |
| [pynput](./LIB-19.yaml) | ホットキーを受け付け、貼り付けのキーを仮想的に送信する |
| [pycaw](./LIB-17.yaml) | Windows のシステム音量を読み書きする |
| [comtypes](./LIB-5.yaml) | 音量を操作するスレッドで COM を初期化する |
| [nvidia-cublas-cu12](./LIB-12.yaml) | GPU での文字起こしに使う cuBLAS の DLL |
| [nvidia-cudnn-cu12](./LIB-14.yaml) | GPU での文字起こしに使う cuDNN の DLL |
| [nvidia-cuda-nvrtc-cu12](./LIB-13.yaml) | GPU での文字起こしに使う NVRTC の DLL |
| [Microsoft Edge](./LIB-2.yaml) | ブラウザ添付のプリセットの画面をアプリのウィンドウとして開く |
| [fastapi](./LIB-7.yaml) | 常駐サービスの API のルートと入出力の検証を組み立てる |
| [uvicorn](./LIB-29.yaml) | API を 127.0.0.1 で待ち受ける |
| [httpx](./LIB-9.yaml) | 起こした文字を呼び出し元のエンドポイントへ返す |
| [pydantic](./LIB-18.yaml) | 設定と API の入出力を検証する |
| [pyside6-essentials](./LIB-21.yaml) | 画面とトレイを出し、ほかのスレッドからメインスレッドへ操作を渡す |
| [tomlkit](./LIB-28.yaml) | 前のバージョンの settings.toml を、settings.yaml へ移すために読む |
| [ruamel.yaml](./LIB-25.yaml) | 設定をコメントを保ったまま YAML で読み書きする |
| [platformdirs](./LIB-16.yaml) | 設定・履歴・ログの置き場所を Windows の慣習で引く |
| [import-linter](./LIB-10.yaml) | 新しい構成の import の向きを検査する |
| [av](./LIB-4.yaml) | faster-whisper が録音を読むために使う、FFmpeg の Python バインディング |
| [pywin32](./LIB-24.yaml) | テストが Windows のウィンドウ・マウス・キーを操作する |
| [onnxruntime](./LIB-15.yaml) | 連続録音の話し声を Silero VAD の ONNX で判定する |
| [python-multipart](./LIB-22.yaml) | ブラウザから送信された multipart の音声を FastAPI の UploadFile で受け取る |
| [python-xlib](./LIB-23.yaml) | Linux でアクティブなウィンドウの WM_CLASS を Xorg から読む |
| [evdev](./LIB-6.yaml) | Linux の Wayland のセッションで、仮想キーボードから貼り付けのキーと Enter を送信する |
| [Focused Window D-Bus](./LIB-1.yaml) | Linux の Wayland のセッションで、フォーカスしているウィンドウの wm_class を GNOME Shell の拡張から読む |
| [Open JTalk](./LIB-3.yaml) | Linux の非機能要件テストで、録音の入力にする文を WAV に書き出す |
| [haas_asr](./LIB-30.yaml) | WSL の文字起こしのサーバーで、Haas-ja-v1.0 のモデルで音声を文字に起こす |
| [NeMo](./LIB-31.yaml) | haas_asr がモデルの推論に使う |

<!-- /table -->
