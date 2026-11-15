# テストの全件実行の workflow を develop で初めて回し、E2E と skip の件数を確認する

## 概要

develop に入った workflow `test.yml` を初めて起動し、E2E テストと、ランナーでの単体・結合テストの全件実行の結果を確認する。

## 背景

[Issue #319](https://github.com/shuhei1101/voice-paste/issues/319) の要望。
[PR #318](https://github.com/shuhei1101/voice-paste/pull/318) で作った workflow は、`workflow_dispatch` が既定のブランチ develop にある workflow だけを起動できるため、#318 の中では一度も起動していない。
#318 は develop へマージ済みで、外部ライブラリの設計書 LIB-34〜36 の `verification` は `未確認` のまま残っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [CI](./CI.md) | workflow を初めて回して確認する計画書 |
