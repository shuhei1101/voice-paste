# 文字起こしのエンジンに OpenAI API を追加し、faster-whisper・nvidia-* を入れなくても使えるようにする

## 概要

ユーザーが設定で文字起こしのエンジンに OpenAI API を選び、faster-whisper・nvidia-* を入れていない環境でも常駐アプリを起動して文字に起こせるようにする。
`local_whisper` を使う今の環境の動きは変えない。

## 背景

[Issue #197](https://github.com/shuhei1101/voice-paste/issues/197) の要望。
文字起こしのエンジンは `local_whisper`（faster-whisper）だけで、GPU（CUDA）が無い端末では遅い。
Linux 対応（[#196](https://github.com/shuhei1101/voice-paste/issues/196)）で使う予定の Ubuntu の端末と検証の VM には NVIDIA の GPU が無く、ユーザーは Linux では OpenAI API で文字起こしする予定。
OpenAI のエンジンは、作り直し（[#31](https://github.com/shuhei1101/voice-paste/pull/31)）でユーザーが使わないため消し、エンジンの型だけを残していた。
OpenAI の API キーは、ユーザーが開発の端末（WSL）と検証の VM の `~/.config/voice-paste/secrets/openai_api_key` に置いてある（[コメント](https://github.com/shuhei1101/voice-paste/issues/197#issuecomment-6450313901)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（エンジンの設定・OpenAI のエンジン・依存の extra への分離・VAD のモデルの置き場所・起動のバッチファイル） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない。OpenAI の文字起こしの API は刷新前の `voice_paste_legacy` で動いていた。依存の extra は uv の標準の機能）
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースの流れを変えない）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [ ] 単一ユースケース設計
- [x] ~~モック作成~~（設定画面に既存の欄と同じ種類の項目を追加するだけで、designer が決める見た目が無い）
- [x] ~~インターフェース定義設計~~（影響なし: API の入出力を変えない。OpenAI の失敗はエンジンの失敗として既存の異常系に入る）
- [x] ~~部品設計~~（部品を変えない）
- [ ] 画面設計
- [ ] モジュール構成設計
- [ ] ドキュメント修正
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
