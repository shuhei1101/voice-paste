# E2E の常駐アプリを offscreen でなく実機の画面で起こし、画面・トレイの E2E が待機中を読めるようにする

## 概要

E2E が起こす常駐アプリを実機の Windows の画面で起動し、画面・トレイ・ホットキーの E2E がトレイの待機中を読んで流れるようにする。

## 背景

[Issue #63](https://github.com/shuhei1101/voice-paste/issues/63) の E2E の不備。
release PR [#52](https://github.com/shuhei1101/voice-paste/pull/52)（Sprint v0.3.0、[#55](https://github.com/shuhei1101/voice-paste/pull/55)・[#58](https://github.com/shuhei1101/voice-paste/pull/58)・[#60](https://github.com/shuhei1101/voice-paste/pull/60) の修正を含む `40f0f0c`）で E2E を再実行すると、画面・トレイ・ホットキーを使うケースが、録音を始める前に `start_app` の `wait_tray_state(IDLE)` で `トレイが 待機中 にならなかった（今は None）` によって fail した。

- 結合テストの画面のために `tests/conftest.py` が `QT_QPA_PLATFORM=offscreen` を設定し、`tests/support/real_service.py` の `spawn_process` がそれを常駐アプリへそのまま渡す。E2E の常駐アプリは画面もトレイも実機に出さない
- 同じ起動で `QT_QPA_PLATFORM=offscreen` を付けると UI Automation のトレイのヒントは `[]`、外すと `['待機中']` を返す
- offscreen の設定は [#37](https://github.com/shuhei1101/voice-paste/pull/37) で入り、それ以降の画面・トレイの E2E は実機の画面で流れていなかった

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリ（E2E の支えのコード）の計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない。offscreen を外すとトレイのヒントを読めることは Issue #63 で確かめ済み）
- [x] ~~複合ユースケース設計~~（影響なし: 流れを変えない）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] ~~単一ユースケース設計~~（影響なし: 振る舞いを変えない）
- [x] ~~モック作成~~（利用者に見える画面の見た目を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API の入出力を変えない）
- [x] ~~部品設計~~（画面を変えない）
- [x] ~~画面設計~~（画面を変えない）
- [x] ~~モジュール構成設計~~（影響なし: 常駐アプリのクラス・関数を変えない。直すのは E2E の支えのコード）
- [ ] ドキュメント修正（dev/設計書/テスト/テスト実行方法.yaml）
- [x] ~~単体テスト作成~~（アプリの関数を変えない）
- [x] ~~実装~~（常駐アプリを変えない。直すのは E2E の支えのコードで、E2E テスト作成で扱う）
- [x] ~~結合テスト作成~~（インターフェース定義と画面設計を変えない。結合テストの offscreen の設定も変えない）
- [ ] E2E テスト作成