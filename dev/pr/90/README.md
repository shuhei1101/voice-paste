# 複合 UC の E2E を #78 で変わった返送の中身と save_recording の引数に追従させる

## 概要

複合ユースケースの E2E 3 件を、#78 で変わった返送の中身（`segment_number`・`segment_count`）と `save_recording` の引数に追従させ、release/v0.4.0 の E2E を pass させる。

## 背景

[Issue #83](https://github.com/shuhei1101/voice-paste/issues/83) の E2E 失敗。
release PR [#81](https://github.com/shuhei1101/voice-paste/pull/81)（Sprint v0.4.0 の E2E、[#79](https://github.com/shuhei1101/voice-paste/issues/79)）の [実行の結果](https://github.com/shuhei1101/voice-paste/pull/81#discussion_r4237548252) で、既存の複合ユースケースの 3 件が fail した。

- [#78](https://github.com/shuhei1101/voice-paste/pull/78) で返送の中身に `segment_number`・`segment_count` が入り（`continuous` を指定しない開始では `null`）、`save_recording` に 3 つ目の位置引数 `segment_number` が足された
- 実装は設計書どおりで、テストの期待の辞書と `tests/support/inprocess.py` の `break_saved_recordings` の差し替えが追従していない（切り分け: テスト不備）
- #78 で足した連続録音の E2E は 7 件すべて pass している

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリ（複合ユースケースの E2E とその支えのコード）の計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: シナリオは変わらず、対応テストを実装に追従させるだけ）
- [x] ~~デザインスタイル選定~~（画面を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] ~~単一ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~モック作成~~（画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: 返送の中身は設計書どおりで変えない）
- [x] ~~部品設計~~（画面を変えない）
- [x] ~~画面設計~~（画面を変えない）
- [x] ~~モジュール構成設計~~（影響なし: 常駐アプリのクラス・関数を変えない）
- [x] ~~ドキュメント修正~~（更新するドキュメントが無い）
- [x] ~~単体テスト作成~~（常駐アプリの関数を変えない）
- [x] ~~実装~~（常駐アプリを変えない。直すのは E2E とその支えのコードで、E2E テスト作成で扱う）
- [x] ~~結合テスト作成~~（インターフェース定義と画面設計を変えない）
- [ ] E2E テスト作成