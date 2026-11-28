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

## 実装

設計書『テスト実行方法』に補足「画面の起動」を追加し、開発ドキュメントサーバーの行と起動の手順を記載した。

記載した手順のコードブロックを、作業 PR の worktree の直下でそのまま順に実行して確認した。

| 確認 | 結果 |
| --- | --- |
| project-index（18786）と dev-docs（18787）が起動し、配信元 `voice-input`・`knowledge` を配信する | 起動した。`project-index.log` の `配信中` の行は `['voice-input', 'knowledge']` |
| 重ねた `nav` が配信元の設定になる | `nav.yaml` の最初のタブ名を書き換えて起動し直すと、`/sources/voice-input/config` の `nav.tabs[].title` が書き換えた名前になった（確認の後に元へ戻した） |
| 作業ブランチの画面が開く | `http://127.0.0.1:18787/voice-input/docs/test-procedure/TP-1.yaml?rev=docs/test-procedure/add-dev-docs-screen-launch` がブランチの選択とタブ・サイドバーつきで描かれた |
| 止め方で起動したものだけが止まる | 18786・18787 の待ち受けが無くなり、利用者の端末の 8781・8786 は待ち受けたまま |

## テスト結果

単体・結合テストは無し。変更は設計書『テスト実行方法』の補足だけで、`tests/`・`src/`・`haas_server/` のどのファイルも `docs/test-procedure/TP-1.yaml` の補足を参照しないため。
