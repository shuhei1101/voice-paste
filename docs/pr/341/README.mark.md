# テストの workflow で、実行するテストのファイルを指定して回せるようにする

## 概要

planner が、作業 PR で決めた結合テストの実行範囲の表のファイルだけを、テストの workflow でランナーに回させられるようになる。

## 背景

[Issue #340](https://github.com/shuhei1101/voice-paste/issues/340) の要望。
結合テストの層（テスト実行方法 TL-2）は実行場所が `runner` だが、`.github/workflows/test.yml` の `workflow_dispatch.inputs` は `layer` だけで、層の全件しか回せない。
判定フローチャート『結合テストの実行範囲』は `run_runner` の `{結合テストのパス}` に実行する結合テストを並べる前提のため、作業 PR [#339](https://github.com/shuhei1101/voice-paste/pull/339) では表の範囲を手元の個別実行（`run_one`）で回した。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [要件の表](./要件.yaml) | 影響するユースケース・更新ドキュメント・スコープ外 |
| [タスク一覧](./タスク一覧.yaml) | 工程ごとの状態 |
| [CI](./CI.mark.md) | CI の計画書 |
