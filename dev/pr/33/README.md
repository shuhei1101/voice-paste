# セッションと API を作る

## 概要

ほかのシステムが API で録音を開始・停止・完了し、指定したエンドポイントで起こした文字を受け取れるようにする。
あわせて、録音から出力までの流れと、入口をまたいで同時に 1 つだけ動かす排他をセッションに持たせる。

## 背景

[Issue #19](https://github.com/shuhei1101/voice-paste/issues/19) の要望。
作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の `dev/pr/12/方針決め/`）の目的 1 で、移行の Issue の並びの順 6 にあたる。
土台は [#16](https://github.com/shuhei1101/voice-paste/issues/16)（[#28](https://github.com/shuhei1101/voice-paste/pull/28)）、文字起こし・補正・履歴は [#17](https://github.com/shuhei1101/voice-paste/issues/17)（[#31](https://github.com/shuhei1101/voice-paste/pull/31)）、録音と音量は [#18](https://github.com/shuhei1101/voice-paste/issues/18)（[#32](https://github.com/shuhei1101/voice-paste/pull/32)）で置いてある。
セッション・API サーバー・呼び出し元への返送のモジュール構成とインターフェース定義は [#14](https://github.com/shuhei1101/voice-paste/issues/14)（[#26](https://github.com/shuhei1101/voice-paste/pull/26)）で `status: planned` として起こしてある。
今の `voice_paste_legacy` は録音から出力までが 1 つの関数に続けて書かれ、文字起こしだけをほかのシステムへ渡す境界が無い（方針の記録のリスクと対策）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] ~~PoC 検証~~（FastAPI・uvicorn・httpx は外部ライブラリの設計書で 2026-10-01 に動作を確かめてあり、未検証の技術機構に依存しない）
- [ ] 複合ユースケース設計
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [ ] 単一ユースケース設計
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [ ] インターフェース定義設計
- [x] ~~部品設計~~（画面を作らない）
- [x] ~~画面設計~~（画面を作らない。トレイ・ダイアログでの知らせ方は [#21](https://github.com/shuhei1101/voice-paste/issues/21)）
- [ ] モジュール構成設計
- [ ] ドキュメント修正（設計書/ER図・設計書/非機能要件・設計書/テスト/テスト実行方法）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
