# CI

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/interface/IF-15.yaml](https://github.com/shuhei1101/voice-paste/blob/e317d0118be7ad9370447451743c3e7b5c414c08/docs/interface/IF-15.yaml) | テストの全件実行の workflow の入力・制約・フロー | 入力は `layer` だけ。更新対象 |
| ドキュメント | [docs/test-procedure/TP-1.yaml](https://github.com/shuhei1101/voice-paste/blob/e317d0118be7ad9370447451743c3e7b5c414c08/docs/test-procedure/TP-1.yaml) | テストの層ごとの実行コマンド | TL-2 の `run_runner` は `-f layer=integration` だけ。更新対象 |
| 実装 | [.github/workflows/test.yml](https://github.com/shuhei1101/voice-paste/blob/e317d0118be7ad9370447451743c3e7b5c414c08/.github/workflows/test.yml) | テストの全件実行の workflow | step「層の全件を回す」は `pytest "tests/$LAYER"` だけ |
| テスト | [tests/e2e/workflow/test_test_yml.py](https://github.com/shuhei1101/voice-paste/blob/e317d0118be7ad9370447451743c3e7b5c414c08/tests/e2e/workflow/test_test_yml.py) | IF-15 の対応テスト | パスを指定したフローのテストを追加する |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| workflow の入力 | `workflow_dispatch.inputs` に、実行するテストのパスを空白区切りで受ける任意の文字列の入力を追加する | 入力名は `paths`。`tests/{層}/` の外のパスか `..` を含むパスがあれば、pytest を実行せずに失敗にする |
| テストの実行 | 入力が空なら `tests/{層}`、空でなければ入力のパスを pytest へ指定する。入力の値は `env` で受けて step に展開する | 上限の時間・タイムアウト・成果物は層の値のまま |
| step の名前 | step「層の全件を回す」を「テストを回す」にする | パスを指定したときは全件を回さないため |
| テスト実行方法 | TL-2 の `run_runner` を、`{結合テストのパス}` を入力に指定して起動するコマンドにする | TL-1 は変えない |
| 対応テスト | IF-15 に追加するフローの対応テストを `tests/e2e/workflow/test_test_yml.py` に追加する | workflow が develop へ入った後に回す |

## 設計書の確定コミット

| 工程 | 範囲 | 補足 |
| --- | --- | --- |
| インターフェース定義設計 | `e317d01..790ce08` | TP-1 の TL-2 の `run_runner` も同じ commit で修正した |
| インターフェース定義設計 | `1396e6b..c4f300b` | レビューの指摘の修正 |

## テスト結果

### 単体

なし。
変更したファイルは workflow・設計書・PR ドキュメント・`files.yml` だけで、規約『V字モデル』の対応表で対応する単体テストが無い。

### lint

| コマンド | 結果 | 補足 |
| --- | --- | --- |
| `uv lock --check`・`actionlint` | ✅ | `テスト結果/20261120211237_ee690b1_lint.log`<br>`lint-imports`・`npm run typecheck`・`npm run lint`・`app.js` の再生成の確認は、変更したファイルが Python のコードと画面のスクリプトに触れないため回していない |

### 結合テストの実行範囲

| 変更したファイル | 結果 | 実行する結合テスト | 結合テストが無いエントリーポイント |
| --- | --- | --- | --- |
| `.github/workflows/test.yml` | R7 | - | テストの全件実行（IF-15）。対応テストは E2E テスト（TL-6）の `tests/e2e/workflow/test_test_yml.py` で確認する |
| `docs/interface/IF-15.yaml` | R7 | - | - |
| `docs/test-procedure/TP-1.yaml` | R7 | - | - |
| `files.yml` | R7 | - | - |
| `docs/pr/341/` の各ファイル | R7 | - | - |

結合テスト（TL-2）は実行しない。

- 影響しない: `tests/integration/` に、変更したファイルを参照する結合テストは無い（`test.yml`・`IF-15` で検索して 0 件）
- 結合テストが無い: IF-15 の対応テストは E2E テストの層にあり、結合テスト作成の工程で `tests/e2e/workflow/test_test_yml.py` に追加したフローのテストを足して回す
