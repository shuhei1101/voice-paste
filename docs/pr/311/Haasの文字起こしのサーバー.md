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
| コードの置き場所 | `__init__.py`・`main.py`・`app.py`・`audio.py` を中身を変えずに移す | 分け方は `未確定`（[要件](./要件.md)） |
| 起動スクリプト | 移した後も、受けた引数を全て `haas_server.main` へ引き渡し、環境の python を絶対パスで起動する | import の方法は `未確定`（[要件](./要件.md)） |
| マニフェスト | 依存・`uv.lock` の中身は変えない | `package` を変えるかは import の方法で決まる |
| テスト | テストのコードの import 文（`haas_server.*`）は変えず、常駐アプリの `.venv` から移した後のコードを import できるようにする | 結合テストの別プロセスの起動も同じ検索先で動かす |
| 設計書 | MOD-98〜101・LAY-1 のパスと図を移した後の構成に更新する | - |
| 動作環境 | サーバーの環境の置き場所・Python 3.11・ログの置き場所は変えない | - |

## テスト結果

なし
