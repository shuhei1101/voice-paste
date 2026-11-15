# CI

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/test-procedure/TP-1.yaml](https://github.com/shuhei1101/voice-paste/blob/d11904a4f041e5ab6fafe26d5a30014b054b9232/docs/test-procedure/TP-1.yaml) | テスト実行方法 | どの層も `location`・`run_runner` を持たない。全件実行は手元の Windows の `.venv/Scripts/python.exe` で回す |
| ドキュメント | [docs/architecture/ARCH-1.yaml](https://github.com/shuhei1101/voice-paste/blob/d11904a4f041e5ab6fafe26d5a30014b054b9232/docs/architecture/ARCH-1.yaml) | アーキテクチャ図 | `subsystems` に workflow を持つサブシステムが無い |
| ドキュメント | [docs/layout/LAY-1.yaml](https://github.com/shuhei1101/voice-paste/blob/d11904a4f041e5ab6fafe26d5a30014b054b9232/docs/layout/LAY-1.yaml) | フォルダ構成 | `.github/` のエントリが無い |
| 実装 | `.github/workflows/` | テストを回す workflow | develop に `.github/` が無い |
| テスト | [tests/unit/](https://github.com/shuhei1101/voice-paste/tree/d11904a4f041e5ab6fafe26d5a30014b054b9232/tests/unit) | 単体テスト（バック） | 外部依存なし。Win32 に依存するテストは Linux で、Linux の単一インスタンスのテストは Windows で skip する |
| テスト | [tests/integration/](https://github.com/shuhei1101/voice-paste/tree/d11904a4f041e5ab6fafe26d5a30014b054b9232/tests/integration) | 結合テスト（バック） | マイク・システム音量・文字起こしのエンジンは Mock。画面のテストは offscreen の QApplication で開く |
| テスト | [tests/nfr/](https://github.com/shuhei1101/voice-paste/tree/d11904a4f041e5ab6fafe26d5a30014b054b9232/tests/nfr) | 非機能要件テスト | NVIDIA GPU と git 管理外の `tests/nfr/fixtures/` を使用する |
| テスト | [tests/external/](https://github.com/shuhei1101/voice-paste/tree/d11904a4f041e5ab6fafe26d5a30014b054b9232/tests/external) | 外部疎通テスト | 外部サービスの認証情報と、Windows の実機の再生デバイスを使用する |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| 層の実行場所 | 判定フローチャート『テストの実行場所』で層ごとに判定し、テスト実行方法の `location` に記載する | 判定の結果は `### 層の実行場所の判定` |
| 手元でしか動かないテスト | `runner` の層のうち、手元でしか用意できないものを使用するテストにマーカーを付け、ランナーの全件実行から除く。マーカーは `pyproject.toml` の `markers` に登録する | インターフェース定義設計で洗い出し、該当するテストは無かった（マーカーは作らない） |
| workflow のインターフェース定義 | 起動契機が `workflow_dispatch` のインターフェース定義を作り、入力・道具の導入・テストの実行・ログの取得の step と分岐を記載する | 要件の「ランナーの OS」「workflow の分け方」 |
| workflow | 合格したインターフェース定義のとおりに `.github/workflows/` へ作る | push・PR を契機にしない |
| `run_runner` | `runner` の層ごとに、workflow を起動して終わるまで待ち、失敗したときもログを取得してから失敗で終える 1 コマンドを記載する | - |
| lint | lint の層の全件実行に actionlint を加える | - |
| タイムアウト | 判定フローチャート『タイムアウトの決め方』で決める | 値はインターフェース定義に記載する |
| アーキテクチャ図 | workflow を持つサブシステムと、GitHub Actions との境界を追加する | 要件の「workflow を持つ対象システム」 |
| フォルダ構成 | `.github/workflows/` のエントリを追加する | - |
| この作業 PR の全件実行 | workflow が develop に無いため手元で回し、回せなかった理由をログに記載する | 単体・結合テストの層の全件は、タイムアウトの値を決める実測のために回した（インターフェース定義の「タイムアウトの決め方」） |

### 層の実行場所の判定

判定フローチャート『テストの実行場所』の判定の結果。

| 層 | lint か | 手元でしか用意できないもの | 外部へ実際に接続 | workflow で道具を入れられる | 実行場所 |
| --- | --- | --- | --- | --- | --- |
| 単体テスト（バック） | NO | NO | NO | YES（uv） | `runner` |
| 結合テスト（バック） | NO | NO（外部は Mock） | NO | YES（uv） | `runner` |
| 非機能要件テスト | NO | YES（NVIDIA GPU・git 管理外の fixtures。層の大半が使用する） | - | - | `local` |
| 外部疎通テスト | NO | YES（外部サービスの認証情報・実機の再生デバイス） | - | - | `local` |
| lint | YES | - | - | - | `local` |

## 設計書の確定コミット

| 工程 | 範囲 | 補足 |
| --- | --- | --- |
| インターフェース定義設計 | `d11904a..3ca35c4` | アーキテクチャ図・外部ライブラリの設計書とテスト実行方法の層の実行場所を含む |
| インターフェース定義設計 | `9330ddb..f21f116` | レビューの指摘の修正（対応テスト・pytest-timeout・GitHub Actions の外部システム連携・目次の表のマーカー） |
| ドキュメント修正 | `f46b7ab..59c24db` | フォルダ構成の `.github/workflows/`（レビューの指摘の修正を含む） |
| インターフェース定義設計 | `7e904a5..9b26b23` | 実装で、step「層の全件を回す」の `uv run` に `--frozen` を付けた |

## テスト結果

### ドキュメント修正

なし。
フォルダ構成（LAY-1）の修正だけで、規約『V字モデル』の対応表で関係する単体・結合テストは無い。

### 実装

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| lint（テスト実行方法の lint の層の全件） | 全実行 | 実行のみ | ✅ | `uv lock --check`・`lint-imports`・`tsc`・ESLint・`app.js` の再生成・actionlint の全てが終了コード 0<br>`テスト結果/20261115155256_36f8695_lint.log` |

単体・結合テストは回していない。
変更したファイル（`.github/workflows/test.yml`・`pyproject.toml`・`uv.lock`）は、規約『V字モデル』の対応表で対応する単体・結合テストを持たない。
`pyproject.toml` に足した pytest-timeout は、`--timeout` を渡したときだけテストに上限を設けるため、手元の全件実行の結果を変えない。
workflow の対応テスト（`tests/e2e/workflow/test_test_yml.py`）は工程『結合テスト作成』で作る。

### 結合テスト作成

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| `tests/e2e/workflow/test_test_yml.py` | 全実行 | 新規 | - | 5 テストを収集し、`--run-e2e` が無いときに全て skip することを確認した<br>`テスト結果/20261115161423_9d03fe0_結合テスト.log` |
| lint（テスト実行方法の lint の層の全件） | 全実行 | 実行のみ | ✅ | 全ての検査が終了コード 0<br>`テスト結果/20261115161446_9d03fe0_lint.log` |

E2E テストの層（`--run-e2e`）は回していない。
workflow `test.yml` が develop に無く、`gh workflow run` が `HTTP 404: workflow test.yml not found on the default branch` で断られるため（ログの先頭）。
5 つのフローは、この workflow が develop へ入った後に `--run-e2e` で回す。

レビューの指摘で、各テストがフローの図の全ての step の結論を丸ごと比べる形に直した（`9d03fe0`）。
