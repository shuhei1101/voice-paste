# CI

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/test-procedure/TP-1.yaml](https://github.com/shuhei1101/voice-paste/blob/2848e5fd9dfc21c44db064c4156b6463c27dee6c/docs/test-procedure/TP-1.yaml) | テスト実行方法 | TL-1・TL-2 の `run_runner` は、`run_id` を取った直後に `gh run watch` を呼ぶ |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| run の参照の待ち | TL-1・TL-2 の `run_runner` で、`run_id` を取った後、`gh api "repos/{owner}/{repo}/actions/runs/$run_id?exclude_pull_requests=true"` が成功するまで 1 秒おきに試し、10 回で参照できなければ `実行 {run_id} を 10 秒参照できません` を標準エラーに出して終了コード 1 で終える | project-index の TP-1・claude-balancer の TP-275-1 の `run_runner` と同じ待ち方 |
| 動作の確認 | 書き換えた TL-1 の `run_runner` を作業ブランチで 1 回流し、集計の行を受け取れることを確認する | - |

## テスト結果

### 単体

コードを変更しないため、関係する単体テストは無い。
書き換えた TL-1 の `run_runner` の確認として、作業ブランチで単体テストの層の全件をランナーで回した。

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| `tests/unit/` | 全実行 | 実行のみ | ✅ | 938 テスト pass・57 skip。run を参照してから `gh run watch` が終わるまで待ち、集計の行を受け取れた（[実行 44057189443](https://github.com/shuhei1101/voice-paste/actions/runs/44057189443)）<br>`テスト結果/20261117184907_9730237_単体テスト.log` |

### 結合

なし（コードを変更しない）
