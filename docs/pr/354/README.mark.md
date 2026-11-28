# テスト実行方法に、作業ブランチの配信の設定で開発ドキュメントサーバーの画面を開く手順を追加する

## 概要

配信の設定を変えた作業 PR で、planner と reviewer が、テスト実行方法の補足「画面の起動」の手順で作業ブランチの配信の設定の開発ドキュメントサーバーの画面を開けるようにする。

## 背景

[Issue #352](https://github.com/shuhei1101/voice-paste/issues/352) の要望。
planner『実装』の「配信の設定の画面の撮影」と reviewer のレビューは、設計書『テスト実行方法』（[docs/test-procedure/TP-1.yaml](https://github.com/shuhei1101/voice-paste/blob/936236b/docs/test-procedure/TP-1.yaml)）の補足「画面の起動」の開発ドキュメントサーバーの行の手順で画面を開くが、この補足が無く、作業のたびに起動の方法を調べ直している。
[作業 PR #351](https://github.com/shuhei1101/voice-paste/pull/351) のレビューで、reviewer が対象外の逸脱として報告した（[報告](https://github.com/shuhei1101/voice-paste/pull/351#discussion_r4726748539)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
