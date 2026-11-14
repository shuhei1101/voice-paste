# 開発コマンドに AI Monitor の publish・generate を加え、フォルダ構成の生成物に generated_from を記載する

## 概要

開発者が、目次・ナビゲーション・生成した Markdown を再生成するコマンドを開発コマンドから引けるようにし、フォルダ構成の設計書の生成物から生成元とコマンドを辿れるようにする。

## 背景

[Issue #304](https://github.com/shuhei1101/voice-paste/issues/304) の要望。
開発コマンドの設計書 `docs/dev-command/CMD-1.yaml` に、`docs/README.md`・`docs/{種類}/README.md`・`docs/_theme/_data/nav.project.yml` を書き出す AI Monitor の `python -m ai_monitor.design_docs publish` と、`docs/generated/` を生成する `generate` が無い。
そのため、フォルダ構成の設計書 `docs/layout/LAY-1.yaml` で、これらの生成物に `generated_from` を記載できない。
[PR #300](https://github.com/shuhei1101/voice-paste/pull/300)（起点 [Issue #269](https://github.com/shuhei1101/voice-paste/issues/269)）の設計書を、knowledge の規約『フォルダ構成の切り方とレビュー』の観点「管理しないもの」で確認して見つかった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
