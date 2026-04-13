# voice-paste

## 概要

音声入力＆自動貼り付けツール。マイクで喋った内容をリアルタイムで文字起こしし、アクティブなアプリに自動貼り付け・送信する常駐型ツール。

## 主な機能

- **ホットキーで録音開始**（常駐モード対応）
- **faster-whisper（large-v3）** による高精度な文字起こし（GPU/CPU対応）
- **3つの確定モード**: 貼付+送信 / 貼付のみ / コピーのみ
- **用語集CSV** による誤変換の修正
- **トレイアイコン** で状態表示（白=待機 / 赤=録音中 / 青=文字起こし中）
- **設定GUI** からホットキー・Whisperモデル・ウィンドウ位置等を変更可能
- **履歴保存** 録音WAVと文字起こしテキストを日付フォルダに自動保存・自動削除
- **デュアルモニター対応** カーソルがあるモニターにウィンドウを表示

## 配布・インストール

### exe版（推奨）

`dist/voice-paste/` フォルダをそのまま配布する。

```
voice-paste/
├── voice-paste.exe    ← 実行ファイル
├── _internal/         ← ランタイム・モデル等（必須）
│   ├── resources/
│   │   ├── prompt.txt
│   │   └── yogo.csv
│   └── .env.sample
├── .env               ← 初回起動時に .env.sample からコピーされる
├── log/               ← ログ出力先（自動生成）
├── cache/             ← 一時ファイル（自動生成）
└── history/           ← 履歴保存先（自動生成）
```

- `voice-paste.exe` をダブルクリックで起動
- 初回起動時に `.env.sample` から `.env` が自動生成される
- **必要なもの**: NVIDIA GPU + CUDAドライバ（GPU モードの場合）
- **CPU のみの場合**: `.env` で `WHISPER_DEVICE=cpu`、`WHISPER_COMPUTE_TYPE=int8` に変更

### 開発環境からの起動

```
setup\setup_venv.bat    # venv作成・依存インストール
run.bat                 # コンソール付きで起動
run_tray.bat            # バックグラウンドで起動
```

### ビルド

```
setup\build_exe.bat
```

## 使い方

### 基本操作

1. 起動するとタスクトレイに常駐（白丸アイコン）
2. `Ctrl+Alt+D` で録音開始（波形ウィンドウ表示、赤丸に変化）
3. 録音を確定:
   - `Ctrl+Alt+D` → **貼付+送信**（ペースト後Enterも送信）
   - `Ctrl+Alt+V` → **貼付のみ**（ペーストのみ）
   - `Ctrl+Alt+C` → **コピー**（クリップボードにコピーするだけ）
4. 文字起こし実行（トレイアイコンが青丸に変化）
5. 結果が自動的に貼り付けられる

### キャンセル

- `Esc` キー（ウィンドウフォーカス時）
- `Ctrl+Alt+Q`（グローバルホットキー）

### 用語集

`resources/prompt.txt` に自由テキストで文脈を記載できる。

`resources/yogo.csv` に誤変換→正しい表記の対応を記載すると、Whisperの認識精度が向上する:

```csv
誤変換,正しい表記
ふぁすたーびすぱー,faster-whisper
ぼいすぺーすと,voice-paste
```

### 設定

タスクトレイの右クリックメニュー → 「設定」で GUI から変更可能。
`.env` ファイルを直接編集しても反映される。

## 設定一覧（.env）

### Whisper モデル

| 設定 | デフォルト | 説明 |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | モデルサイズ |
| `WHISPER_DEVICE` | `cuda` | デバイス（cuda / cpu） |
| `WHISPER_COMPUTE_TYPE` | `float16` | 量子化タイプ |
| `WHISPER_BEAM_SIZE` | `10` | ビームサーチ幅（精度↑/速度↓） |
| `WHISPER_BEST_OF` | `5` | サンプリング候補数 |
| `WHISPER_LANGUAGE` | `ja` | 認識言語 |
| `WHISPER_VAD_FILTER` | `true` | 無音区間除去 |
| `WHISPER_VAD_THRESHOLD` | `0.5` | 音声判定の確信度閾値 |
| `WHISPER_VAD_MIN_SPEECH_MS` | `250` | 最小音声長（ms） |
| `WHISPER_VAD_MIN_SILENCE_MS` | `2000` | 最小無音長（ms）※改行位置に影響 |
| `WHISPER_TEMPERATURE` | `0.0` | サンプリング温度 |

### ホットキー

| 設定 | デフォルト | 説明 |
|---|---|---|
| `RESIDENT_HOTKEY` | `Ctrl+Alt+D` | 録音開始 |
| `CONFIRM_HOTKEY` | `Ctrl+Alt+D` | 貼付+送信 |
| `CONFIRM_PASTE_ONLY_HOTKEY` | `Ctrl+Alt+V` | 貼付のみ |
| `COPY_ONLY_HOTKEY` | `Ctrl+Alt+C` | コピーのみ |
| `CANCEL_HOTKEY` | `Ctrl+Alt+Q` | キャンセル |

### その他

| 設定 | デフォルト | 説明 |
|---|---|---|
| `PASTE_ENTER_DELAY` | `0.5` | 貼付→送信の待機秒数 |
| `HISTORY_ENABLED` | `true` | 履歴保存のON/OFF |
| `HISTORY_RETENTION_DAYS` | `1` | 履歴の保持日数 |
| `WINDOW_TOPMOST` | `true` | 常に最前面 |
| `WINDOW_POSITION` | `center` | 表示位置 |
| `WINDOW_FOLLOW_CURSOR` | `true` | カーソル側モニターに表示 |
| `WINDOW_HIDDEN` | `false` | ウィンドウ非表示モード |

## 開発技術

- **Python** 3.11以上
- **faster-whisper** — 音声文字起こし（GPU/CPU対応）
- **sounddevice** — マイク録音
- **scipy** — 録音データのWAVファイル保存
- **pyperclip** — クリップボードへのテキストコピー
- **pynput** — キーボード仮想入力・グローバルホットキー
- **pystray** — システムトレイアイコン
- **Pillow** — トレイアイコン画像生成
- **tkinter** — GUI（標準ライブラリ）
- **PyInstaller** — exe ビルド

## フォルダ構成

```
voice-paste/
├── voice_paste/
│   ├── transcription/
│   │   ├── transcribable.py       # 文字起こしインターフェース
│   │   └── whisper_transcriber.py # faster-whisper実装
│   ├── audio/
│   │   └── recorder.py            # マイク録音・WAVファイル保存
│   ├── input/
│   │   └── keyboard_sender.py     # pynputによるキー送信
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py                  # .env 設定読み込み
│   ├── main.py                    # エントリーポイント
│   ├── gui.py                     # 録音モーダルウィンドウ
│   ├── settings_gui.py            # 設定ウィンドウ
│   ├── tray.py                    # システムトレイアイコン
│   ├── history.py                 # 履歴保存・自動削除
│   ├── logger.py
│   ├── exceptions.py
│   ├── constants.py
│   └── utils.py                   # プロンプト・用語集読み込み
├── resources/
│   ├── prompt.txt                 # Whisperプロンプト（用語集）
│   └── yogo.csv                   # 誤変換修正CSV
├── setup/
│   ├── setup_venv.bat
│   └── build_exe.bat
├── tests/
├── dist/                          # ビルド出力先
├── run.bat
├── run_tray.bat
├── .env.sample
└── pyproject.toml
```

## ライセンス

MIT
