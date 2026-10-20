# pyproject.toml の改行を LF に揃え、uv add / uv remove で全行が差分にならないようにする

## 概要

`pyproject.toml` の改行を LF に揃え、`uv add` / `uv remove` で依存を 1 つ変えたときに全行が改行の差分にならないようにする。

## 背景

[Issue #140](https://github.com/shuhei1101/voice-paste/issues/140) の要望。
`pyproject.toml` は index で 1〜78 行が CRLF、79 行以降（`[[tool.importlinter.contracts]]`）が LF の混在（`git ls-files --eol` で `i/mixed`）で、`uv add` / `uv remove` が全行を LF で書き直すため、依存を 1 つ足すだけで全行が改行の差分になる。
[作業 PR #139](https://github.com/shuhei1101/voice-paste/pull/139)（[Issue #116](https://github.com/shuhei1101/voice-paste/issues/116)）のレビューの[対象外の逸脱の報告](https://github.com/shuhei1101/voice-paste/pull/139#discussion_r4320228537)から切り出した。
[作業 PR #142](https://github.com/shuhei1101/voice-paste/pull/142)（[Issue #119](https://github.com/shuhei1101/voice-paste/issues/119)）で `.gitattributes`（`* text=auto eol=lf`）が入ったが、既にあるファイルを正規化していないため、混在は残っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: アプリの振る舞いを変えない）
- [x] ~~デザインスタイル選定~~（画面を変えない）
- [x] ~~画面一覧・画面遷移~~（画面を変えない）
- [x] ~~単一ユースケース設計~~（影響なし: アプリの振る舞いを変えない）
- [x] ~~モック作成~~（画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API と JSON Lines の入出力を変えない）
- [x] ~~部品設計~~（画面を変えない）
- [x] ~~画面設計~~（画面を変えない）
- [x] ~~モジュール構成設計~~（影響なし: コードを変えない）
- [x] ドキュメント修正（dev/設計書/開発コマンド/開発コマンド.yaml）
- [x] ~~単体テスト作成~~（コードを変えない）
- [ ] 実装
- [x] ~~結合テスト作成~~（インターフェース定義と画面設計を変えない）
- [x] ~~E2E テスト作成~~（シナリオを変えない）
