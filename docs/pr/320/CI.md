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
| ランナーでの全件実行 | 作業ブランチで `TL-1`・`TL-2` の `run_runner` を回し、ログを `テスト結果/` に配置する | 件数の比べ方は `### 件数の比較

| 層 | 手元（Windows） | ランナー（`windows-latest`） | 違いの原因 |
| --- | --- | --- | --- |
| 単体テスト（バック） | 937 passed・57 skipped | 比べられない（ジョブの準備で失敗し、テストを実行していない） | `### 初回の起動で分かったこと` |
| 結合テスト（バック） | 807 passed・1 skipped | 比べられない（同上） | 同上 |

### 初回の起動で分かったこと

workflow の全ての実行が、ジョブの準備（Set up job）の `Unable to resolve action astral-sh/setup-uv@v10, unable to find version v10` で失敗した。
`astral-sh/setup-uv` はメジャーバージョンのタグ（`v10`）を公開しておらず、タグは `v10.3.3` のような完全なバージョンだけ（`gh api repos/astral-sh/setup-uv/git/ref/tags/v10` は 404）。
`actions/checkout@v7`・`actions/upload-artifact@v7` のタグは存在する。
LIB-35 の `version.pinning` の「メジャーバージョンのタグで指定する」が、この action では成り立たない。

## テスト結果

### 単体

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| `tests/unit/` | 全実行 | 実行のみ | ❌ | ランナーのジョブの準備で失敗し、テストは実行していない（[実行](https://github.com/shuhei1101/voice-paste/actions/runs/43692966298)）<br>`テスト結果/20261115170640_98a9cb9_単体テスト.log` |

### 結合

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| `tests/integration/` | 全実行 | 実行のみ | ❌ | 単体と同じ原因で失敗<br>`テスト結果/20261115170645_98a9cb9_結合テスト.log` |

### E2E

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| [tests/e2e/workflow/test_test_yml.py](https://github.com/shuhei1101/voice-paste/blob/98a9cb9/tests/e2e/workflow/test_test_yml.py) | 全実行 | 実行のみ | ❌ | 5 件とも、単体と同じ原因で実行の結論が `failure`・step の結論が空になり fail。Windows の gh が未ログインのため、WSL の Python で実行した<br>`テスト結果/20261115170635_98a9cb9_E2Eテスト.log` |
