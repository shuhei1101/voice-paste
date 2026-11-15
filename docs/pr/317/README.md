# モックと直下のファイルの files.yml の行に、抜けているタグと description を付ける

## 概要

`docs/mock/files.yml` と `docs/_root/files.yml` の、タグか description を持たない行にタグと description を付け、モックと直下のファイルを単語で検索できるようにする。

## 背景

[Issue #316](https://github.com/shuhei1101/voice-paste/issues/316) の要望。
[#285](https://github.com/shuhei1101/voice-paste/issues/285) の作業 PR [#315](https://github.com/shuhei1101/voice-paste/pull/315) で、YAML の設計書とコード・テストの `files.yml` の行にタグと description を付けたとき、モック・直下のファイルの `files.yml` をスコープ外にした。
`docs/mock/files.yml` の 2 行は [#288](https://github.com/shuhei1101/voice-paste/issues/288) で行を足したときに `tags` が抜けた。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
