# dev-docs.yaml の目次の検査から PR ドキュメントの反映作業の一覧を除外する

## 概要

dev-docs の目次（`index`）の検査の対象から、PR ドキュメントの反映作業の一覧 `docs/pr/{PR 番号}/反映作業/index.yaml` を除外する。

## 背景

[Issue #280](https://github.com/shuhei1101/voice-paste/issues/280) の不具合。
`dev-docs.yaml` の `id: index` の行は `paths: ["docs/**/index.yaml"]` で `exclude` を持たないため、目次ではない反映作業の一覧まで `schemas/index.schema.yaml` で検査され、`search_docs` の notes にスキーマ違反が出る。
[#279](https://github.com/shuhei1101/voice-paste/pull/279) の作業中に気づき、スコープ外として切り出した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
