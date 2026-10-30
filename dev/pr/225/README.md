# OpenAI の既定のモデルを gpt-4o-mini-transcribe の提供終了の前に後継へ変える

## 概要

ユーザーが OpenAI API のエンジンを、`gpt-4o-mini-transcribe` の提供終了（2027-02-26）の後も既定のモデルのまま使い続けられるようにする。
settings.toml で前のモデルを指定したユーザーの設定も、そのまま動く。

## 背景

[Issue #206](https://github.com/shuhei1101/voice-paste/issues/206) の要望。
[#204](https://github.com/shuhei1101/voice-paste/pull/204) で OpenAI API のエンジンの既定のモデル（設定 `transcription.openai.model`）を、ユーザーの判断で `gpt-4o-mini-transcribe` にした（[確認事項のスレッド](https://github.com/shuhei1101/voice-paste/pull/204#discussion_r4397499388)）。
`gpt-4o-mini-transcribe` は 2027-02-26 に提供が終わる（[Deprecations](https://developers.openai.com/api/docs/deprecations)）。
後継の `gpt-transcribe` は、言語を `language` ではなく `languages[]` で受け、手がかりの語を `keywords[]` でも受ける。
使うモデルの検討と疎通確認の求め（[#213](https://github.com/shuhei1101/voice-paste/issues/213)）は、この Issue へ集約された。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（既定のモデル・モデルごとの手がかりと言語の渡し方） |
| [確認ログ](./確認ログ.md) | ユーザーへの確認事項の決着 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない。後継のモデルの要求は同じ `POST /audio/transcriptions` のフォームの項目の違いで、疎通は外部疎通テストで確かめる）
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースの流れを変えない）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] 単一ユースケース設計
- [x] ~~モック作成~~（画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API の入出力を変えない）
- [x] ~~部品設計~~（部品を変えない）
- [x] ~~画面設計~~（影響なし: 設定画面の `transcription.openai.model` は文字の欄のままで、欄の種類と文言を変えない）
- [ ] モジュール構成設計
- [ ] ドキュメント修正
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
