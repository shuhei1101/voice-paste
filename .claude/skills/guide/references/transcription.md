# 文字起こし（faster-whisper）

## ファイル一覧

| ファイル | 概要 |
|---------|------|
| `voice_paste/transcription/transcribable.py` | 文字起こしの抽象基底クラス（インターフェース定義） |
| `voice_paste/transcription/whisper_transcriber.py` | faster-whisperによる文字起こし実装 |
| `resources/prompt.txt` | 用語集・専門用語のヒントテキスト |

## faster-whisper概要

- **ライブラリ**: `faster-whisper` （CTranslate2ベースの高速Whisper推論）
- **モデルロード**: 常駐モードではメモリ保持、ワンショットでは毎回ロード
- **入力**: WAV音声ファイル + 用語集プロンプト
- **出力**: セグメント結合テキスト

## よくある改修

- **文字起こしパラメータ調整**: `.env` のWHISPER_*設定を変更
- **用語集の更新**: `resources/prompt.txt` を編集
- **文字起こしロジック変更**: `voice_paste/transcription/whisper_transcriber.py` を編集
- **別の文字起こしエンジン追加**: `transcribable.py` のインターフェースを実装する新クラスを作成
