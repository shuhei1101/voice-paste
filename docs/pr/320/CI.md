# CI

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| 実装 | [.github/workflows/test.yml](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/.github/workflows/test.yml) | テストの全件実行の workflow | develop に入ったが、一度も起動していない |
| ドキュメント | [docs/interface/IF-15.yaml](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/docs/interface/IF-15.yaml) | テストの全件実行 | 補足「フローの確認方法」に、develop へ入った後に対応テストファイルを回すと書いている |
| ドキュメント | [docs/test-procedure/TP-1.yaml](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/docs/test-procedure/TP-1.yaml) | テスト実行方法 | 単体テスト（バック）・結合テスト（バック）の `run_runner` と、E2E テストの層（`TL-6`）を持つ |
| ドキュメント | [docs/library/LIB-34.yaml](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/docs/library/LIB-34.yaml) | actions/checkout | `verification.state` が `未確認` |
| ドキュメント | [docs/library/LIB-35.yaml](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/docs/library/LIB-35.yaml) | astral-sh/setup-uv | `verification.state` が `未確認` |
| ドキュメント | [docs/library/LIB-36.yaml](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/docs/library/LIB-36.yaml) | actions/upload-artifact | `verification.state` が `未確認`。`catalogs` の引数は `docs_only` |
| テスト | [tests/e2e/workflow/test_test_yml.py](https://github.com/shuhei1101/voice-paste/blob/6d346f3449025f05e8ddc97e55dcb947f094a052/tests/e2e/workflow/test_test_yml.py) | workflow test.yml の E2E テスト | 一度も回していない |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| E2E テスト | `TL-6` の全件実行のコマンドで回し、ログを `テスト結果/` に配置する | 検証用のブランチはテストが終わりに削除する |
| ランナーでの全件実行 | 作業ブランチで `TL-1`・`TL-2` の `run_runner` を回し、ログを `テスト結果/` に配置する | 件数の比べ方は `### 件数の比較` に記載する |
| 外部ライブラリの確認状態 | LIB-34〜36 の `verification` を `済` にし、日付と、どの実行で何を確認したかを `detail` に記載する。LIB-36 の `catalogs` の引数は、成果物 `test-log` が上がったことで確認できたものを `verified` にする | fail して確認できなかった action は `未確認` のまま残し、理由を `detail` に記載する |
| fail・件数の違い | 原因を調べて `### 件数の比較` に書き、修正する作業を別の Issue にする | workflow・テスト・コードは変えない |

### 実行するテスト

この作業 PR はコードを変えず、変更ファイルは PR ドキュメントと LIB-34〜36 だけ。
起点 Issue が求める確認として、次だけを回す。非機能要件テスト・外部疎通テストは回さない。

| テスト | 範囲 | 実行場所 | 範囲の理由 |
| --- | --- | --- | --- |
| `tests/e2e/workflow/test_test_yml.py` | 全 5 件（IF-15 のフロー） | 手元から `gh` で GitHub Actions を起動する | 成功・失敗・タイムアウト・導入の失敗の経路で、LIB-34〜36 の action を 1 回ずつ実行する |
| 単体テスト（バック） | 層の全件（`run_runner`） | ランナー（`windows-latest`） | skip の件数を手元の全件実行と比べるのが起点 Issue の要望で、層の全件でないと比べられない。手元の資源は使用しない |
| 結合テスト（バック） | 層の全件（`run_runner`） | ランナー（`windows-latest`） | 単体テスト（バック）と同じ |

### 件数の比較

ランナーの結果を回した後に記入する。

| 層 | 手元（Windows） | ランナー（`windows-latest`） | 違いの原因 |
| --- | --- | --- | --- |
| 単体テスト（バック） | 937 passed・57 skipped | 未実行 | - |
| 結合テスト（バック） | 807 passed・1 skipped | 未実行 | - |

## テスト結果

未実行。
