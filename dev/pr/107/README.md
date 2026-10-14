# 設定の保存で配列の表の後ろのコメントを消さない

## 概要

設定を保存しても、`settings.toml` の配列の表（`[[hint_presets]]`・`[[glossaries]]`・`[[outputs]]`）の後ろに書いたコメントが消えないようにし、release/v0.5.0 の E2E を pass させる。

## 背景

[Issue #105](https://github.com/shuhei1101/voice-paste/issues/105) の E2E 失敗。
release PR [#102](https://github.com/shuhei1101/voice-paste/pull/102)（Sprint v0.5.0 の E2E、[#93](https://github.com/shuhei1101/voice-paste/issues/93)）の [実行の結果](https://github.com/shuhei1101/voice-paste/pull/102#discussion_r4269366777) で、`tests/e2e/単一ユースケース/test_change_settings.py::test_normal_when_edit_hint_presets` が fail した（保存前に書いた `# E2E: このコメントは保存しても残る` が `settings.toml` から消える）。

- tomlkit は配列の表の後ろのコメントを、最後の要素の中のものとして読む
- `save_settings` の `_merge_into` は配列を丸ごと入れ替えるため、古い要素と一緒にそのコメントも消える（切り分け: 実装バグ）
- シナリオ『設定を変える』は「ほかのキーとコメントが変わっていない」を求めている

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリ（設定の書き戻し）の計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースは設定の保存を通らない）
- [x] ~~デザインスタイル選定~~（画面を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] ~~単一ユースケース設計~~（影響なし: シナリオ『設定を変える』は既にコメントを保つことを求めている）
- [x] ~~モック作成~~（画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: インターフェースを変えない）
- [x] ~~部品設計~~（画面を変えない）
- [x] ~~画面設計~~（画面を変えない）
- [x] モジュール構成設計
- [x] ~~ドキュメント修正~~（更新するドキュメントが無い）
- [x] 単体テスト作成
- [ ] 実装
- [x] ~~結合テスト作成~~（インターフェース定義と画面設計を変えない）
- [x] ~~E2E テスト作成~~（既存の `test_normal_when_edit_hint_presets` が確かめており、テストを変えない）