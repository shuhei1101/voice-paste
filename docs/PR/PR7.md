# PR7: OpenAI APIモードでのセグメント単位改行対応

## 概要

現在の OpenAI APIモードは `response_format="text"` で一括テキストを返すだけで、
ローカル（faster-whisper）のようなセグメント単位の改行・コールバックがない。
`response_format="verbose_json"` に変更してセグメントを `\n` 結合し、
ローカルと同じ出力形式にする。

## 作業内容

- [ ] `openai_transcriber.py` を `response_format="verbose_json"` に変更
- [ ] セグメント配列を `\n` 結合（ローカルの `WhisperTranscriber` と同じ形式）
- [ ] `on_segment` コールバックをセグメントごとに呼ぶよう変更
  （現在は完了後に1回だけ呼んでいる）

## 実装メモ

- `verbose_json` レスポンスの `segments[].text` を strip して `\n` 結合
- `on_segment` は各セグメント処理後に呼び出す（オーバーレイアニメーション更新）
- `temperature` パラメーターは引き続き `config.WHISPER_TEMPERATURE` を使用
- `language` は引き続き `config.WHISPER_LANGUAGE` を使用

## テスト

- [ ] 複数セグメントある発話でセグメント間が改行されること
- [ ] 単一セグメントでも正常動作すること
- [ ] `on_segment` コールバックがセグメントごとに呼ばれること（オーバーレイ更新）
