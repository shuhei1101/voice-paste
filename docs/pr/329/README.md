# 開発ドキュメントのはじめに・使い方・リファレンスのタブを category で自動に並べる

## 概要

`docs/guide/files.yml` に公開ドキュメントを追加した人が、`dev-docs.yaml` の `nav` を書き換えずに、その文書を `category` のタブ（はじめに・使い方・リファレンス）で開発ドキュメントサーバーに出せるようにする。

## 背景

[Issue #328](https://github.com/shuhei1101/voice-paste/issues/328) の要望。
[PR #327](https://github.com/shuhei1101/voice-paste/pull/327) で `dev-docs.yaml` に `nav` を追加し、はじめに・使い方・リファレンスのタブは `docs/guide/files.yml` の文書を `page` で 1 件ずつ並べている（[#327 のレビューの指摘](https://github.com/shuhei1101/voice-paste/pull/327#discussion_r4594649207)）。
`files.yml` の行は `category` を持つが、`category` は knowledge の `schemas/knowledge-files.schema.yaml` に無い項目のため、`auto.filter` の `field: category` で絞れない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
