# develop に入っている作業 PR のスクリーンショットを削除する

## 概要

squash マージで develop に入った作業 PR のスクリーンショットを、履歴を書き換えない削除の commit で消す。

## 背景

[Issue #283](https://github.com/shuhei1101/voice-paste/issues/283) の要望。作業 PR のスクリーンショット（`docs/pr/*/スクリーンショット/`）が develop に入り、リポジトリが重くなっている（origin/develop で 20 個の PR フォルダに 1465 ファイル・約 118MB）。
これからのスクリーンショットは Git 管理外に置く手順に変わり（[shuhei1101/ai-monitor#3373](https://github.com/shuhei1101/ai-monitor/pull/3373)）、既に入った画像は削除の commit を入れるとユーザーが決めた（[確認ログ](https://github.com/shuhei1101/ai-monitor/pull/3373#discussion_r4536950116)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
