# 開発ドキュメントのタブの並びとサイドバーのグループを決まりに従って定義し、目次を並べない

## 概要

開発ドキュメントサーバーで配信元 `voice-input` を開いた人が、入口の文書を左のタブから読み始め、設計書を種類ごとのグループでたどれるようにする。

## 背景

[Issue #324](https://github.com/shuhei1101/voice-paste/issues/324) の要望。
配信元 `voice-input` のタブは `dev-docs.yaml` の `documents` の行ごとに作られて 20 件あり、画面の幅に収まらない。
入口になる公開ドキュメントが右の方にあり、フォルダの目次（`index`）も「目次」のタブとして並んでいる。
決まりは [shuhei1101/knowledge#421](https://github.com/shuhei1101/knowledge/issues/421) で規約『開発ドキュメントのナビゲーション』（`dev-docs-navigation`）として登録済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
