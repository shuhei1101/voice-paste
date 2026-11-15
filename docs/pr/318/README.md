# テスト実行方法の層ごとに実行場所を決め、runner の層を GitHub Actions の workflow で回す

## 概要

テスト実行方法の層ごとに実行場所を決め、`runner` の層を GitHub Actions のランナーで回せるようにする。

## 背景

[Issue #298](https://github.com/shuhei1101/voice-paste/issues/298) の要望。
全プロジェクトの単体・結合テストを同じ端末で回しており、手元のメモリが逼迫している。
voice-paste のテスト実行方法は全ての層を手元で回す前提で、層ごとの実行場所が無く、テストを回す workflow も無い。

層の実行場所を判定してランナーで回す手順と、テンプレート『テスト実行方法』の `location`・`run_runner` は [knowledge#350](https://github.com/shuhei1101/knowledge/issues/350)・[knowledge#351](https://github.com/shuhei1101/knowledge/issues/351)・[ai-monitor#3434](https://github.com/shuhei1101/ai-monitor/issues/3434) で入っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [CI](./CI.md) | テスト実行方法の層の実行場所と、テストを回す workflow の計画書 |
