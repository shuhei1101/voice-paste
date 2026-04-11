# voice-paste — プロジェクト構造

## 概要
音声入力＆自動貼り付けツール（Windows専用、faster-whisper使用）

---

## 機能A: 文字起こし

| ファイル名 | 概要 | ファイルパス |
|------------|------|-------------|
| transcribable.py | 文字起こしインターフェース | voice_paste/transcription/transcribable.py |
| whisper_transcriber.py | faster-whisper実装 | voice_paste/transcription/whisper_transcriber.py |

---

## 機能B: 音声録音

| ファイル名 | 概要 | ファイルパス |
|------------|------|-------------|
| recorder.py | マイク録音・WAVファイル保存（sounddevice + scipy） | voice_paste/audio/recorder.py |

---

## 機能C: キーボード仮想入力

| ファイル名 | 概要 | ファイルパス |
|------------|------|-------------|
| keyboard_sender.py | クリップボードコピー・Ctrl+V / Enter送信（pynput） | voice_paste/input/keyboard_sender.py |

---

## 共通モジュール

| ファイル名 | 概要 | ファイルパス |
|------------|------|-------------|
| config.py | 設定読み込み（.env管理） | voice_paste/config.py |
| main.py | 起動フロー制御 | voice_paste/main.py |
| gui.py | 録音モーダルウィンドウ（tkinter・波形表示） | voice_paste/gui.py |
| logger.py | ログ設定 | voice_paste/logger.py |
| exceptions.py | カスタム例外 | voice_paste/exceptions.py |
| constants.py | 定数定義 | voice_paste/constants.py |
| utils.py | プロンプトファイル読み込み等 | voice_paste/utils.py |

---

## テスト

| ファイル名 | 概要 | ファイルパス |
|------------|------|-------------|
| mock_env.py | 環境変数モック | tests/mocks/mock_env.py |
| mock_externals.py | 外部ライブラリモック（Whisperセグメント等） | tests/mocks/mock_externals.py |
| test_whisper_transcriber.py | 文字起こし統合テスト | tests/transcription/test_whisper_transcriber.py |
