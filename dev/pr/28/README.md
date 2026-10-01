# 作り直しの新しい構成の土台を作る

## 概要

作り直しの新しい構成の土台（`src/voice_paste/` の機能フォルダ型のレイアウト、`shared` の設定とログ、`.env` からの移行の処理、import-linter の検査）を置き、後続の移行の Issue が機能を作り直せるようにする。

## 背景

[Issue #16](https://github.com/shuhei1101/voice-paste/issues/16) の要望。
作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の `dev/pr/12/方針決め/`）の移行の Issue の並びの順 3 にあたる。
あるべき姿の設計書は [#14](https://github.com/shuhei1101/voice-paste/issues/14)（[#26](https://github.com/shuhei1101/voice-paste/pull/26)）で起こし、今のコードは [#15](https://github.com/shuhei1101/voice-paste/issues/15)（[#27](https://github.com/shuhei1101/voice-paste/pull/27)）で `voice_paste_legacy/` へ移して普段使いを続けている。
#26 は設定の設計書（`settings.toml` のキー）と、tomlkit・platformdirs・import-linter の外部ライブラリの設計書、`pyproject.toml` に書く依存の版の決め方をこの Issue へ回している。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] ~~PoC 検証~~（pydantic・tomlkit・platformdirs・import-linter はいずれも単体で使い方が確立したライブラリで、未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 利用者から見える流れは変わらず、普段使いは `voice_paste_legacy` のまま）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [x] ~~単一ユースケース設計~~（影響なし: 常駐アプリを起動するは `settings.toml` を読む形で [#26](https://github.com/shuhei1101/voice-paste/pull/26) が書き終えている。`.env` からの移行は切り替えの反映作業で 1 度だけ行う移行の処理で、利用者の操作の流れではない）
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [x] ~~インターフェース定義設計~~（API・入口を作らない。API は [#19](https://github.com/shuhei1101/voice-paste/issues/19) で作る）
- [x] ~~部品設計~~（画面を作らない）
- [x] ~~画面設計~~（画面を作らない）
- [ ] モジュール構成設計
- [ ] ドキュメント修正（設計書/設定・設計書/外部ライブラリ・設計書/テスト/テスト実行方法）
- [ ] 単体テスト作成
- [ ] 実装
- [x] ~~結合テスト作成~~（入口・外部との境界を作らない。import-linter の検査は単体テストと一緒に回す）
- [x] ~~E2E テスト作成~~（利用者の操作の流れが変わらない）