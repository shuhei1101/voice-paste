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

## 画面確認

作業ブランチの `dev-docs.yaml` を作業ツリーから読む project-index（`storage.type: disk`）と、それにつないだ dev-docs を別ポートで立て、画面を 1440x900 で撮った。
project-index の起動時の検査で、voice-input の `nav` の警告（`知らない項目です（category）`・当たる文書が 0 件の `auto`）は出なかった。
はじめに・使い方・リファレンスのタブは、`page` で並べた文書だけが並ぶ（`auto` は同じタブの `page` の文書を除く）。
`docs/guide/files.yml` に `category: 使い方` の文書を一時的に足すと、`nav` を書き換えずに使い方のタブの末尾に出た（確認後に一時の文書は消した）。

| 画面 | スクリーンショット |
| --- | --- |
| 一時の文書を足した使い方 | [1-使い方-確認用の文書あり_1440x900.png](./画面確認/1-使い方-確認用の文書あり_1440x900.png) |
| はじめに | [2-はじめに_1440x900.png](./画面確認/2-はじめに_1440x900.png) |
| 使い方 | [3-使い方_1440x900.png](./画面確認/3-使い方_1440x900.png) |
| リファレンス | [4-リファレンス_1440x900.png](./画面確認/4-リファレンス_1440x900.png) |

## テスト結果

単体・結合テストは無し。変更は開発ドキュメントの配信の設定だけで、アプリのコードとテストが参照しないため。
