# ログ

## ファイル一覧

| ファイル | 概要 |
|---------|------|
| `voice_paste/logger.py` | ロガー初期化（コンソール + ファイルハンドラ） |

## ログ設定

- **ロガー名**: `voice_paste`
- **ログレベル**: `.env` の `LOG_LEVEL` で設定（デフォルト: `INFO`）
- **出力先**:
  - コンソール（stdout）: `[日時] LEVEL module - message`
  - ファイル: `log/YYYYMMDDHHMMSS_voice_paste.log`（ファイル名・行番号付き）
- **DLLデバッグログ**: `log/dll_debug.log`（PyInstaller実行時のみ）

## よくある改修

- **ログレベル変更**: `.env` の `LOG_LEVEL` を変更（またはGUIから）
- **ログフォーマット変更**: `voice_paste/logger.py` を編集
- **ログ出力先追加**: `voice_paste/logger.py` にハンドラ追加
