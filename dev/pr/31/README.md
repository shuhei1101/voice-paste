# 文字起こし・補正・履歴を新しい構成で作り直す

## 概要

文字起こし（ローカルの Whisper の文字起こしワーカーと OpenAI）・用語集の補正・履歴を `src/voice_paste/` の新しい構成で作り直し、刷新前と同じ文字を起こせて、ワーカーが落ちても録音が履歴に残るようにする。

## 背景

[Issue #17](https://github.com/shuhei1101/voice-paste/issues/17) の要望。
作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の `dev/pr/12/方針決め/`）の移行の Issue の並びの順 4 にあたる。
土台（`src/voice_paste/` のレイアウト・設定のモデル・ログ・import-linter）は [#16](https://github.com/shuhei1101/voice-paste/issues/16)（[#28](https://github.com/shuhei1101/voice-paste/pull/28)）で置き、刷新前の文字起こしと補正の特性テストは [#15](https://github.com/shuhei1101/voice-paste/issues/15)（[#27](https://github.com/shuhei1101/voice-paste/pull/27)）で `voice_paste_legacy` に対して固めている。
あるべき姿のモジュール構成（文字起こし・補正・履歴・外部連携・文字起こしワーカー）は [#14](https://github.com/shuhei1101/voice-paste/issues/14)（[#26](https://github.com/shuhei1101/voice-paste/pull/26)）で `status: planned` として起こしてある。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
| [文字起こしワーカー](./文字起こしワーカー.md) | 文字起こしワーカーの計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] ~~PoC 検証~~（文字起こしワーカーの子プロセス・faster-whisper・OpenAI の文字起こしは `voice_paste_legacy` で動いている形を移すもので、未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 普段使いは `voice_paste_legacy` のままで、録音から出力までをつなぐのはセッションを作る [#19](https://github.com/shuhei1101/voice-paste/issues/19)）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [x] ~~単一ユースケース設計~~（影響なし: 録音を文字に起こすは新しい構成の形で [#26](https://github.com/shuhei1101/voice-paste/pull/26) が書き終えている）
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [x] ~~インターフェース定義設計~~（API・入口を作らない。API は [#19](https://github.com/shuhei1101/voice-paste/issues/19) で作る）
- [x] ~~部品設計~~（画面を作らない）
- [x] ~~画面設計~~（画面を作らない。文字起こし中の表示は [#21](https://github.com/shuhei1101/voice-paste/issues/21)）
- [x] モジュール構成設計
- [x] ドキュメント修正（設計書/ER図・設計書/非機能要件・設計書/外部ライブラリ・設計書/テスト/テスト実行方法）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成（OpenAI の疎通テスト）
- [x] ~~E2E テスト作成~~（利用者の操作の流れが変わらず、対象のシナリオが `tests/e2e/` のテストファイルを持たない）