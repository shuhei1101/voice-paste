# voice-paste プロジェクト

Whisper ベースの音声入力→文字起こし→自動貼り付けツール（Windows 常駐）。

## フォルダ構成

```
voice-paste/
├── .env / .env.sample        # 設定ファイル
├── pyproject.toml             # パッケージ定義・依存関係
├── run.bat / run_tray.bat     # 実行スクリプト
├── resources/
│   └── prompt.txt             # 文字起こし用語集プロンプト
├── voice_paste/               # メインパッケージ
│   ├── __main__.py            # エントリーポイント（DLL登録）
│   ├── main.py                # アプリケーションフロー制御
│   ├── config.py              # 設定読み込み（.env → モジュール変数）
│   ├── constants.py           # パス定数・デフォルト値
│   ├── logger.py              # ログ初期化
│   ├── exceptions.py          # カスタム例外定義
│   ├── utils.py               # ユーティリティ（プロンプト読み込み等）
│   ├── gui.py                 # 録音モーダルウィンドウ
│   ├── settings_gui.py        # 設定ウィンドウ
│   ├── tray.py                # システムトレイアイコン
│   ├── audio/
│   │   └── recorder.py        # マイク録音・WAV保存
│   ├── transcription/
│   │   ├── transcribable.py   # 文字起こしインターフェース（ABC）
│   │   └── whisper_transcriber.py  # faster-whisper実装
│   └── input/
│       └── keyboard_sender.py # クリップボード・仮想キーボード入力
├── tests/                     # テストコード
├── setup/                     # セットアップ・ビルドスクリプト
├── log/                       # ログ出力先（実行時生成）
└── cache/                     # 一時音声ファイル（実行時生成）
```

## アプリケーションフロー

```
起動 → __main__.py（DLL登録）→ main.py:run()
 ├─ 常駐モード: トレイ常駐 + ホットキー待機 → ループ
 └─ ワンショット: 1回だけ実行して終了

1回の実行フロー:
  録音開始 → モーダル表示（波形）→ 確定/キャンセル
  → 音声ファイル保存 → faster-whisper文字起こし
  → クリップボード → 貼り付け（+ Enter）
```

**スレッド構成**: メインスレッド（tkinter + ディスパッチキュー）、トレイスレッド（pystray）、ホットキースレッド（pynput）

## 外部ライブラリ

定義ファイル: `pyproject.toml`

| ライブラリ           | バージョン | 用途                                 | 関連ファイル                                                       |
| -------------------- | ---------- | ------------------------------------ | ------------------------------------------------------------------ |
| `faster-whisper`     | ~=1.0      | 音声文字起こしエンジン               | `transcription/whisper_transcriber.py`                             |
| `sounddevice`        | ~=0.5      | マイク音声入力                       | `audio/recorder.py`                                                |
| `scipy`              | ~=1.13     | WAVファイル読み書き                  | `audio/recorder.py`                                                |
| `pyperclip`          | ~=1.9      | クリップボード操作                   | `input/keyboard_sender.py`                                         |
| `pynput`             | ~=1.7      | グローバルホットキー・仮想キーボード | `main.py`, `gui.py`, `settings_gui.py`, `input/keyboard_sender.py` |
| `python-dotenv`      | ~=1.0      | .env読み込み                         | `config.py`, `settings_gui.py`                                     |
| `pystray`            | ~=0.19     | システムトレイアイコン               | `tray.py`                                                          |
| `Pillow`             | >=11.0     | トレイアイコン画像処理               | `tray.py`                                                          |
| `nvidia-cublas-cu12` | —          | CUDA線形代数（GPU高速化）            | ランタイム依存                                                     |
| `nvidia-cudnn-cu12`  | >=9,<10    | CUDA DNN（GPU推論）                  | ランタイム依存                                                     |

### ライブラリ更新・追加

- **バージョン更新**: `pyproject.toml` の依存バージョンを変更 → `pip install -e .`
- **新規追加**: `pyproject.toml` の `dependencies` に追加

## 実装ルール

- 実装の内部詳細はソースコードを直接読んで確認する
- 編集対象のサブディレクトリに `CLAUDE.md` があれば、それが該当領域のより詳細なガイド
