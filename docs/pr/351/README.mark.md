# 開発ドキュメントのサイドバーで、入れ子にすべきグループを入れ子にする

## 概要

開発ドキュメントサーバーで配信元 `voice-input` を開いた人が、サイドバーの入れ子のグループから設計書とコードを探せるようにする。

## 背景

[Issue #349](https://github.com/shuhei1101/voice-paste/issues/349) の要望。
project-index の `nav` の `group` は、子の `items[]` に `group` を持てる（入れ子にできる）ようになった。
この配信元の `project-index.yaml` の `nav` は、[#324](https://github.com/shuhei1101/voice-paste/issues/324)（[#327](https://github.com/shuhei1101/voice-paste/pull/327)）で定義したグループが 1 段だけで、入れ子を使っていない。
設定ファイルの名前は [#348](https://github.com/shuhei1101/voice-paste/issues/348)（[#350](https://github.com/shuhei1101/voice-paste/pull/350)）で `dev-docs.yaml` から `project-index.yaml` へ改名済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
