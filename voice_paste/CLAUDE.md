# voice_paste パッケージ

メインパッケージ。設定・GUI・ログの概要はこのファイル。
文字起こし固有の内容は `transcription/CLAUDE.md` を参照。

## 設定（.env / config.py / settings_gui.py）

設定ファイル: `.env`（テンプレート: `.env.sample`）
読み込み: `voice_paste/config.py`
GUI 編集: `voice_paste/settings_gui.py`

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

### 設定の編集

- **値の変更**: `.env` を直接編集、または `settings_gui.py` の GUI から
- **項目の追加**: `.env.sample` にデフォルト値 → `config.py` に読み込みロジック追加
- **GUI に項目追加**: `settings_gui.py` の `SettingsWindow.show()` にウィジェット追加

---

## GUI（gui.py / settings_gui.py / tray.py）

| ファイル | 概要 |
|---------|------|
| `gui.py` | 録音モーダル — 録音中の波形表示、確定/キャンセルボタン |
| `settings_gui.py` | 設定ウィンドウ — Whisper 設定・ホットキー・ログレベルの変更 UI |
| `tray.py` | システムトレイ — アイコン・メニュー（録音開始/ログ/設定/終了） |

### 技術スタック

- **フレームワーク**: tkinter（標準ライブラリ）
- **トレイ**: pystray + Pillow
- **テーマ**: ダークテーマ（背景 `#1e1e1e`、アクセント `#0078d4`）
- **ホットキー**: pynput リスナー

### よくある改修

- **録音モーダル UI 変更**: `gui.py`
- **設定ウィンドウに項目追加**: `settings_gui.py` の `show()`
- **トレイメニュー変更**: `tray.py`
- **テーマ・色変更**: 各ファイルの色定数（`_BG`, `_FG`, `_ACCENT` 等）

---

## ログ（logger.py）

- **ロガー名**: `voice_paste`
- **ログレベル**: `.env` の `LOG_LEVEL`（デフォルト `INFO`）
- **出力先**:
  - コンソール（stdout）: `[日時] LEVEL module - message`
  - ファイル: `log/YYYYMMDDHHMMSS_voice_paste.log`
- **DLL デバッグログ**: `log/dll_debug.log`（PyInstaller 実行時のみ）

### よくある改修

- **ログレベル変更**: `.env` の `LOG_LEVEL`（または GUI から）
- **ログフォーマット変更**: `logger.py`
- **出力先追加**: `logger.py` にハンドラ追加
