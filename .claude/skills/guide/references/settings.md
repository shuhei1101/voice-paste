# 設定一覧

設定ファイル: `.env`（テンプレート: `.env.sample`）
読み込み: `voice_paste/config.py`

## 設定項目

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

## 設定を編集する場合

- **設定値の変更**: `.env` を直接編集、または `voice_paste/settings_gui.py` のGUIから変更
- **設定項目の追加**: `.env.sample` にデフォルト値追加 → `voice_paste/config.py` に読み込みロジック追加
- **GUIに設定を追加**: `voice_paste/settings_gui.py` の `SettingsWindow.show()` にウィジェット追加
