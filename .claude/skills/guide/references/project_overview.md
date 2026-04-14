# プロジェクト概要

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

## アプリケーションフロー（概要）

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
