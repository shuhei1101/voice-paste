---
name: guide
description: "voice-pasteプロジェクトのガイド。フォルダ構造・設定・GUI・文字起こし・ログなどの概要確認と編集ナビゲーション。"
user_invocable: true
---

# voice-paste ガイド

このプロジェクトの構造を理解し、よく行う改修作業にナビゲートする対話スキル。

**重要**: 内部実装の詳細はソースコードを直接読んで確認すること。このガイドはファイルパスと概要のみ記載。

---

## メインメニュー

ユーザーにメニューを提示し、選択を待つ。引数がある場合はそれに対応するメニュー項目へ直接遷移する。

```
=== voice-paste ガイド ===

1. プロジェクト概要 — フォルダ構成・アプリケーションフロー
2. 設定一覧 — .env設定項目の確認・編集
3. GUI関連 — 録音モーダル・設定ウィンドウ・トレイ
4. 文字起こし（faster-whisper） — Whisperモデル・文字起こし処理
5. 外部ライブラリ — 使用パッケージ一覧
6. ログ — ログ設定・出力先
```

---

## 1. プロジェクト概要

### フォルダ構成

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

### アプリケーションフロー（概要）

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

ユーザーに概要を説明した後、メインメニューに戻るか他の項目を見るか聞く。

---

## 2. 設定一覧

設定ファイル: `.env`（テンプレート: `.env.sample`）
読み込み: `voice_paste/config.py`

### 設定項目

| カテゴリ | キー | 説明 |
|---------|------|------|
| **Whisperモデル** | `WHISPER_MODEL` | 使用モデル（tiny/base/small/medium/large-v3） |
| | `WHISPER_DEVICE` | 実行デバイス（cuda/cpu） |
| | `WHISPER_COMPUTE_TYPE` | 量子化タイプ（float16/int8/float32） |
| | `WHISPER_CPU_THREADS` | CPUスレッド数（0=自動） |
| | `WHISPER_NUM_WORKERS` | 並列デコードワーカー数 |
| | `WHISPER_BEAM_SIZE` | ビームサーチ幅 |
| | `WHISPER_LANGUAGE` | 認識言語（ja等） |
| | `WHISPER_VAD_FILTER` | VAD無音除去（true/false） |
| | `WHISPER_CONDITION_ON_PREVIOUS_TEXT` | 前セグメント文脈使用 |
| | `WHISPER_TEMPERATURE` | サンプリング温度 |
| | `WHISPER_NO_SPEECH_THRESHOLD` | 無音判定閾値 |
| **プロンプト** | `PROMPT_FILE` | 用語集ファイルパス |
| **ログ** | `LOG_LEVEL` | ログレベル（DEBUG/INFO/WARNING/ERROR） |
| **常駐モード** | `RESIDENT_MODE` | 常駐モード切替（true/false） |
| | `RESIDENT_HOTKEY` | 録音開始ホットキー |
| | `CONFIRM_HOTKEY` | 録音確定（ペースト+Enter） |
| | `CONFIRM_PASTE_ONLY_HOTKEY` | 録音確定（ペーストのみ） |
| | `CANCEL_HOTKEY` | 録音キャンセル |

### 設定を編集する場合

- **設定値の変更**: `.env` を直接編集、または `voice_paste/settings_gui.py` のGUIから変更
- **設定項目の追加**: `.env.sample` にデフォルト値追加 → `voice_paste/config.py` に読み込みロジック追加
- **GUIに設定を追加**: `voice_paste/settings_gui.py` の `SettingsWindow.show()` にウィジェット追加

ユーザーが特定の設定を変更したい場合、該当ファイルを読んで案内する。メインメニューに戻るか聞く。

---

## 3. GUI関連

### ファイル一覧

| ファイル | 概要 |
|---------|------|
| `voice_paste/gui.py` | 録音モーダル — 録音中の波形表示、確定/キャンセルボタン |
| `voice_paste/settings_gui.py` | 設定ウィンドウ — Whisper設定・ホットキー・ログレベルの変更UI |
| `voice_paste/tray.py` | システムトレイ — アイコン・メニュー（録音開始/ログ/設定/終了） |

### GUI技術スタック

- **GUIフレームワーク**: tkinter（標準ライブラリ）
- **トレイ**: pystray + Pillow
- **テーマ**: ダークテーマ（背景 `#1e1e1e`、アクセント `#0078d4`）
- **ホットキーキャプチャ**: pynputリスナーによるリアルタイム取得

### よくある改修

- **録音モーダルのUI変更**: `voice_paste/gui.py` を編集
- **設定ウィンドウに項目追加**: `voice_paste/settings_gui.py` の `show()` メソッドにウィジェット追加
- **トレイメニュー変更**: `voice_paste/tray.py` を編集
- **テーマ・色変更**: 各GUIファイルの色定数（`_BG`, `_FG`, `_ACCENT` 等）

ユーザーが具体的なGUI改修を求めた場合、該当ファイルを読んで実装を案内する。メインメニューに戻るか聞く。

---

## 4. 文字起こし（faster-whisper）

### ファイル一覧

| ファイル | 概要 |
|---------|------|
| `voice_paste/transcription/transcribable.py` | 文字起こしの抽象基底クラス（インターフェース定義） |
| `voice_paste/transcription/whisper_transcriber.py` | faster-whisperによる文字起こし実装 |
| `resources/prompt.txt` | 用語集・専門用語のヒントテキスト |

### faster-whisper概要

- **ライブラリ**: `faster-whisper` （CTranslate2ベースの高速Whisper推論）
- **モデルロード**: 常駐モードではメモリ保持、ワンショットでは毎回ロード
- **入力**: WAV音声ファイル + 用語集プロンプト
- **出力**: セグメント結合テキスト

### よくある改修

- **文字起こしパラメータ調整**: `.env` のWHISPER_*設定を変更
- **用語集の更新**: `resources/prompt.txt` を編集
- **文字起こしロジック変更**: `voice_paste/transcription/whisper_transcriber.py` を編集
- **別の文字起こしエンジン追加**: `transcribable.py` のインターフェースを実装する新クラスを作成

ユーザーが具体的な改修を求めた場合、該当ファイルを読んで実装を案内する。メインメニューに戻るか聞く。

---

## 5. 外部ライブラリ

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

### ライブラリ更新・追加

- **バージョン更新**: `pyproject.toml` の依存バージョンを変更 → `pip install -e .`
- **新規追加**: `pyproject.toml` の `dependencies` に追加

ユーザーに一覧を説明した後、メインメニューに戻るか聞く。

---

## 6. ログ

### ファイル一覧

| ファイル | 概要 |
|---------|------|
| `voice_paste/logger.py` | ロガー初期化（コンソール + ファイルハンドラ） |

### ログ設定

- **ロガー名**: `voice_paste`
- **ログレベル**: `.env` の `LOG_LEVEL` で設定（デフォルト: `INFO`）
- **出力先**:
  - コンソール（stdout）: `[日時] LEVEL module - message`
  - ファイル: `log/YYYYMMDDHHMMSS_voice_paste.log`（ファイル名・行番号付き）
- **DLLデバッグログ**: `log/dll_debug.log`（PyInstaller実行時のみ）

### よくある改修

- **ログレベル変更**: `.env` の `LOG_LEVEL` を変更（またはGUIから）
- **ログフォーマット変更**: `voice_paste/logger.py` を編集
- **ログ出力先追加**: `voice_paste/logger.py` にハンドラ追加

ユーザーに説明した後、メインメニューに戻るか聞く。

---

## 動作ルール

1. メニューを表示して選択を待つ
2. 選択された項目の概要を説明する
3. ユーザーが具体的な編集を求めたら、該当ファイルを **Read で読んでから** 案内・実装する
4. 作業後はメインメニューに戻るか聞く
5. 実装の内部詳細はこのスキルに書かず、必ずソースを読んで最新の状態を確認する
