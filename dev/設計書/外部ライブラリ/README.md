# 外部ライブラリ

採用済みの外部ライブラリ / 外部ツールのリファレンス

## 目次

<!-- table: data -->

| ページ | 概要 |
| --- | --- |
| [faster-whisper](./faster-whisper.yaml) | ローカルの Whisper で音声を文字に起こす |
| [sounddevice](./sounddevice.yaml) | マイクの入力を開いて録音する |
| [scipy](./scipy.yaml) | 録音を WAV に読み書きする |
| [numpy](./numpy.yaml) | 録音した音を配列で貯め、音量を求める |
| [pyperclip](./pyperclip.yaml) | 起こした文字をクリップボードへ書く |
| [pynput](./pynput.yaml) | ホットキーを受け付け、貼り付けのキーを仮想的に送る |
| [pycaw](./pycaw.yaml) | Windows のシステム音量を読み書きする |
| [comtypes](./comtypes.yaml) | 音量を操作するスレッドで COM を初期化する |
| [nvidia-cublas-cu12](./nvidia-cublas-cu12.yaml) | GPU での文字起こしに使う cuBLAS の DLL |
| [nvidia-cudnn-cu12](./nvidia-cudnn-cu12.yaml) | GPU での文字起こしに使う cuDNN の DLL |
| [nvidia-cuda-nvrtc-cu12](./nvidia-cuda-nvrtc-cu12.yaml) | GPU での文字起こしに使う NVRTC の DLL |
| [Microsoft_Edge](./Microsoft_Edge.yaml) | ブラウザ添付のプリセットの画面をアプリのウィンドウとして開く |
| [fastapi](./fastapi.yaml) | 常駐サービスの API のルートと入出力の検証を組み立てる |
| [uvicorn](./uvicorn.yaml) | API を 127.0.0.1 で待ち受ける |
| [httpx](./httpx.yaml) | 起こした文字を呼び出し元のエンドポイントへ返す |
| [pydantic](./pydantic.yaml) | 設定と API の入出力を検証する |
| [pyside6-essentials](./pyside6-essentials.yaml) | 画面とトレイを出し、ほかのスレッドからメインスレッドへ操作を渡す |
| [tomlkit](./tomlkit.yaml) | 設定をコメントを保ったまま TOML で読み書きする |
| [platformdirs](./platformdirs.yaml) | 設定・履歴・ログの置き場所を Windows の慣習で引く |
| [import-linter](./import-linter.yaml) | 新しい構成の import の向きを検査する |
| [av](./av.yaml) | faster-whisper が録音を読むために使う、FFmpeg の Python バインディング |
| [pywin32](./pywin32.yaml) | テストが Windows のウィンドウ・マウス・キーを操作する |
| [onnxruntime](./onnxruntime.yaml) | 連続録音の話し声を Silero VAD の ONNX で判定する |

<!-- /table -->
