# 文字起こしのエンジンに WSL で動かす日本語の音声認識モデル Haas-ja-v1.0 を追加する

## 概要

ユーザーが設定で文字起こしのエンジンに Haas-ja-v1.0 を選び、WSL（Linux と NVIDIA GPU）を使用できる環境では faster-whisper より速く精度の高い文字起こしを使用できるようにする。
WSL を使用できない環境では今の faster-whisper のまま動く。

## 背景

[Issue #263](https://github.com/shuhei1101/voice-paste/issues/263) の要望。
文字起こしのエンジンは `local_whisper`（faster-whisper の large-v3）と `openai`（[#204](https://github.com/shuhei1101/voice-paste/pull/204) で追加）の 2 つ。
Haas-ja-v1.0（Third Intelligence、Apache 2.0）は日本語の CER 6.12% で、Whisper large-v3 の約 15〜17 倍速いと発表された。
Haas は Linux と NVIDIA GPU（Triton・CUDA）が必須で、Windows の常駐アプリの中では動かない。
voice-paste は表記のヒントの単語を faster-whisper の `hotwords` に指定している。Haas は `haas_asr.Vocabulary`（表記 → 読みの組）で単語の手がかりを受け付けるが、表記のヒントは読みを持たない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（Haas のエンジン・WSL の文字起こしのサーバー・faster-whisper への切り戻し・設定と設定画面） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] PoC 検証（WSL で Haas を動かし、voice-paste の録音で faster-whisper と精度・速さ・表記のヒントの単語の認識を比べる。Windows の常駐アプリから WSL のサーバーへ HTTP で届くかも確認する）
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースの流れを変えない。エンジンの違いは単一ユースケースの中に収まる）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [ ] 単一ユースケース設計
- [x] ~~モック作成~~（設定画面に既存の欄と同じ種類の項目を追加するだけで、作り手が決める見た目が無い）
- [ ] インターフェース定義設計
- [x] ~~部品設計~~（部品を変えない）
- [ ] 画面設計
- [ ] モジュール構成設計
- [ ] ドキュメント修正
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
