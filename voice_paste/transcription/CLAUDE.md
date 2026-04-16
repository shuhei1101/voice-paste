# 文字起こし（faster-whisper）

## ファイル一覧

| ファイル | 概要 |
|---------|------|
| `transcribable.py` | 文字起こしの抽象基底クラス（インターフェース定義） |
| `whisper_transcriber.py` | faster-whisper による文字起こし実装 |
| `../../resources/prompt.txt` | 用語集・専門用語のヒントテキスト |

## faster-whisper 概要

- **ライブラリ**: `faster-whisper`（CTranslate2 ベースの高速 Whisper 推論）
- **モデルロード**: 常駐モードではメモリ保持、ワンショットでは毎回ロード
- **入力**: WAV 音声ファイル + 用語集プロンプト
- **出力**: セグメント結合テキスト

## 用語集（yogo.csv）の扱い

文字起こしの誤変換を補正する仕組みは **2段構え**:

1. **Whisper への initial_prompt（ヒント）** — `utils.build_initial_prompt` で
   `「X」と聞こえたら「Y」と表記する` 形式の文を生成し、`initial_prompt` として渡す。
   Whisper が必ず従うとは限らない（あくまで推論のヒント）。
2. **後処理の単純置換** — `utils.apply_yogo_replacements` で、文字起こし結果の
   文字列に対して `str.replace(誤変換, 正しい表記)` を適用する。
   これにより Whisper がヒントを無視した場合でも確実に置換される。
   呼び出しは `main.py:_run_once` 内、`transcriber.transcribe()` 直後。

**注意**: 後処理は単純な文字列置換のため、**誤変換側の語が他の文脈にも現れるとそこも
置換される**。固有名詞や一意性の高い語に限って登録すること（例: 部分一致で副作用が
出そうな汎用語は登録しない）。

## よくある改修

- **パラメータ調整**: `.env` の `WHISPER_*` 設定を変更
- **用語集の更新**: `resources/prompt.txt`（自由記述ヒント）または `yogo.csv`（置換ペア）を編集
- **ロジック変更**: `whisper_transcriber.py` を編集
- **別エンジン追加**: `transcribable.py` のインターフェースを実装する新クラスを作成
