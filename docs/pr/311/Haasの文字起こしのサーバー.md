# Haas の文字起こしのサーバー

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/module/MOD-98.yaml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/docs/module/MOD-98.yaml) | サーバーのモジュール構成（フォルダの図・起動スクリプト・テスト・環境の置き場所） | 更新対象 |
| ドキュメント | [docs/module/MOD-99.py.yaml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/docs/module/MOD-99.py.yaml) | FastAPI の app | container のパスを更新 |
| ドキュメント | [docs/module/MOD-100.py.yaml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/docs/module/MOD-100.py.yaml) | 音声の復号 | container のパスを更新 |
| ドキュメント | [docs/module/MOD-101.py.yaml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/docs/module/MOD-101.py.yaml) | 入口とログの設定 | container と起動スクリプトの notes を更新 |
| ドキュメント | [docs/layout/LAY-1.yaml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/docs/layout/LAY-1.yaml) | フォルダ構成の設計書の `haas_server` のエントリ | 更新対象 |
| 実装 | [haas_server/start.sh](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/start.sh) | `haas_server` の親フォルダへ移り、環境の python で `-m haas_server.main` を起動する | 移る先を更新 |
| 実装 | [haas_server/pyproject.toml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/pyproject.toml) | サーバーの環境の依存（`package = false`） | import の方法によって更新 |
| 実装 | [haas_server/main.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/main.py)・[app.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/app.py)・[audio.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/audio.py)・[__init__.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/__init__.py) | サーバーのコード | 移動 |
| 実装 | [haas_server/files.yml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/haas_server/files.yml) | コードの行 | path を更新 |
| テスト | [tests/unit/haas_server/](https://github.com/shuhei1101/voice-paste/tree/7d9ae053c7ce87a869492c465d3ada707cca6a6b/tests/unit/haas_server) | `app`・`audio`・`main` の単体テスト | `haas_server` を import できるようにする |
| テスト | [tests/integration/haas_server/](https://github.com/shuhei1101/voice-paste/tree/7d9ae053c7ce87a869492c465d3ada707cca6a6b/tests/integration/haas_server) | API の結合テストと、別プロセスで `haas_server.main` を動かす `fake_server.py` | 別プロセスでも `haas_server` を import できるようにする |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| コードの置き場所 | `__init__.py`・`main.py`・`app.py`・`audio.py` を中身を変えずに `haas_server/src/haas_server/` へ移動し、`files.yml` を `haas_server/src/files.yml` へ移動する | - |
| 起動スクリプト | `cd "$(dirname "$0")/src"` へ変え、受けた引数を全て `haas_server.main` へ引き渡し、環境の python を絶対パスで起動する | `haas_server/` の直下に配置したまま |
| マニフェスト | 依存・`uv.lock`・`package = false` は変えない | - |
| テスト | テストのコードの import 文（`haas_server.*`）は変えず、直下の `pyproject.toml` の pytest の `pythonpath` に `haas_server/src` を加える | 別のプロセスでサーバーを動かす結合テスト（`test_shutdown.py`）は環境変数 `PYTHONPATH` で同じフォルダを渡す |
| 設計書 | MOD-98〜101・LAY-1 のパスと図を移した後の構成に更新する | - |
| 動作環境 | サーバーの環境の置き場所・Python 3.11・ログの置き場所は変えない | - |

## 設計書の確定コミット

| 工程 | 範囲 | 補足 |
| --- | --- | --- |
| モジュール構成設計 | `7d9ae05..d376e85` | - |

## テスト結果

### 単体

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| [tests/unit/haas_server/](https://github.com/shuhei1101/voice-paste/tree/7d9ae053c7ce87a869492c465d3ada707cca6a6b/tests/unit/haas_server) | 全実行 | 実行のみ | ✅ | 18 テスト pass。移した後の `haas_server/src/haas_server/` を pytest の `pythonpath` で import する<br>`テスト結果/20261114193142_df193eb_単体テスト.log` |
| `tests/unit` の残り | 全実行 | 実行のみ | ✅ | 全体で 937 passed、57 skipped<br>`テスト結果/20261114193142_df193eb_単体テスト.log` |

### 結合

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| [tests/integration/haas_server/test_shutdown.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/tests/integration/haas_server/test_shutdown.py) | 全実行 | 変更 | ✅ | 別のプロセスのサーバーへ `haas_server/src` を `PYTHONPATH` で指定する<br>`テスト結果/20261114193333_145cb77_結合テスト.log` |
| [tests/integration/haas_server/test_transcribe.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/tests/integration/haas_server/test_transcribe.py) | 全実行 | 実行のみ | ✅ | `テスト結果/20261114193333_145cb77_結合テスト.log` |
| [tests/integration/haas_server/test_health.py](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/tests/integration/haas_server/test_health.py) | 全実行 | 実行のみ | ✅ | 3 ファイルで 19 passed<br>`テスト結果/20261114193333_145cb77_結合テスト.log` |

### 起動

| 確認 | 結果 | 補足 |
| --- | --- | --- |
| `wsl.exe -d Ubuntu-24.04 --cd {haas_server/ の Windows のパス} -e bash start.sh --help` | ✅ | 終了コード 0 で `haas_server.main` の使い方を出した。端末で常駐アプリのサーバー（ポート 47824）が GPU を使用しているため、モデルを読み込む起動はしていない |
