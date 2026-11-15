# YAML の設計書とコード・テストの files.yml の行に、タグ・エイリアス・description を付ける

## 概要

YAML の設計書と、コード・テストの `files.yml` の行に、タグ・エイリアス・description を付け、文書を単語で検索できるようにする。

## 背景

[Issue #285](https://github.com/shuhei1101/voice-paste/issues/285) の要望。
[#257](https://github.com/shuhei1101/voice-paste/issues/257) の作業 PR [#282](https://github.com/shuhei1101/voice-paste/pull/282) で文書を mdmark の記載方法へ移したとき、設計書の Schema が `tags`・`aliases` を持たなかったため、タグ・エイリアス・description の記載をスコープ外にした。
[#313](https://github.com/shuhei1101/voice-paste/issues/313)（AI Monitor v0.4.0 への追従）で設計書の Schema が knowledge の `design-schemas/v8.3.0` の参照へ変わり、`tags`・`aliases` を記載できるようになった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの設計書と `src/files.yml`・`tests/files.yml` の計画書 |
| [文字起こしワーカー](./文字起こしワーカー.md) | 文字起こしワーカーの設計書と `files.yml` の行の計画書 |
| [Haas の文字起こしのサーバー](./Haas%20の文字起こしのサーバー.md) | Haas の文字起こしのサーバーの設計書と `haas_server/src/files.yml` の計画書 |
