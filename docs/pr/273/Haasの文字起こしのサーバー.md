# Haas の文字起こしのサーバー

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [dev/設計書/インターフェース定義/Haasの文字起こしのサーバー/音声を文字に起こす.py.yaml](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/Haas%E3%81%AE%E6%96%87%E5%AD%97%E8%B5%B7%E3%81%93%E3%81%97%E3%81%AE%E3%82%B5%E3%83%BC%E3%83%90%E3%83%BC/%E9%9F%B3%E5%A3%B0%E3%82%92%E6%96%87%E5%AD%97%E3%81%AB%E8%B5%B7%E3%81%93%E3%81%99.py.yaml) | `POST /transcriptions` は `audio` と `vocabulary` を受ける | 更新対象 |
| ドキュメント | [dev/設計書/インターフェース定義/Haasの文字起こしのサーバー/準備できたかを返す.py.yaml](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%82%A4%E3%83%B3%E3%82%BF%E3%83%BC%E3%83%95%E3%82%A7%E3%83%BC%E3%82%B9%E5%AE%9A%E7%BE%A9/Haas%E3%81%AE%E6%96%87%E5%AD%97%E8%B5%B7%E3%81%93%E3%81%97%E3%81%AE%E3%82%B5%E3%83%BC%E3%83%90%E3%83%BC/%E6%BA%96%E5%82%99%E3%81%A7%E3%81%8D%E3%81%9F%E3%81%8B%E3%82%92%E8%BF%94%E3%81%99.py.yaml) | `GET /health` はモデルの名前を返却する | 更新対象 |
| ドキュメント | [dev/設計書/モジュール構成/haas_server/main.py.yaml](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%83%A2%E3%82%B8%E3%83%A5%E3%83%BC%E3%83%AB%E6%A7%8B%E6%88%90/haas_server/main.py.yaml) | `HAAS_MODEL_NAME`・`LONGFORM_BATCH_SIZE` の定数 | 更新対象 |
| ドキュメント | [dev/設計書/モジュール構成/haas_server/app.py.yaml](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/dev/%E8%A8%AD%E8%A8%88%E6%9B%B8/%E3%83%A2%E3%82%B8%E3%83%A5%E3%83%BC%E3%83%AB%E6%A7%8B%E6%88%90/haas_server/app.py.yaml) | `SHORT_AUDIO_LIMIT_SEC`・`TranscribeFn`・`BuildVocabularyFn` | 更新対象 |
| 実装 | [haas_server/main.py](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/haas_server/main.py) | モデルの読み込みと `transcribe`・`transcribe_longform` の包み | 定数を引数と要求の値へ |
| 実装 | [haas_server/app.py](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/haas_server/app.py) | `POST /transcriptions` の項目の読み取り | 要求ごとの値の追加 |
| 実装 | [haas_server/start.sh](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/haas_server/start.sh) | ポートだけを `main` へ指定する | 起動の引数の追加 |
| テスト | [tests/unit/haas_server/test_main.py](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/tests/unit/haas_server/test_main.py) | モデルの読み込みと包み | 追加 |
| テスト | [tests/unit/haas_server/test_app.py](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/tests/unit/haas_server/test_app.py) | 項目の読み取り | 追加 |
| テスト | [tests/integration/haas_server/test_transcribe.py](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/tests/integration/haas_server/test_transcribe.py) | `POST /transcriptions` の結合テスト | 追加 |
| テスト | [tests/integration/haas_server/test_health.py](https://github.com/shuhei1101/voice-paste/blob/0e02b4e/tests/integration/haas_server/test_health.py) | `GET /health` の結合テスト | 追加 |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| 起動の引数 | `start.sh` と `main` がポートに続けてモデル・`dtype`・`device` を受け、`haas_asr.load_model` に指定する | 引数が無ければ今の値で起動する |
| 要求の項目 | `POST /transcriptions` が `short_audio_limit_sec`・`batch_size`・`alpha`・`guard`・`chunk_sec`・`search_sec`・`window_sec`・`separator` を multipart の項目で受ける | 項目が無ければ今の値で起こす。範囲の外は 400 |
| 起こし方 | 受けた値を `transcribe`・`transcribe_longform`・`Vocabulary(alpha=...)` に指定する | `batch_size` は `transcribe` にも指定する |
| 準備の確認 | `GET /health` が起動の引数で受けたモデル・`dtype`・`device`（`auto` は解決する前のまま）を返却する | 常駐アプリが設定と文字列で比べる |

## 設計書の確定コミット

| 工程 | 範囲 | 補足 |
| --- | --- | --- |
| インターフェース定義設計 | `40cebdc..40d2119` | - |
| モジュール構成設計 | `5e6bbbc..1489789` | - |

## テスト結果

### 単体

develop（[#274](https://github.com/shuhei1101/voice-paste/pull/274)）の取り込み（[5b56569](https://github.com/shuhei1101/voice-paste/commit/5b56569)）の後に全件（`tests/unit`）を実行し、872 passed・56 skipped。lint は `テスト結果/20261108061111_1d8c0dd_lint.log`（全て exit 0）。

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| [tests/unit/haas_server/test_app.py](https://github.com/shuhei1101/voice-paste/blob/1d8c0dd/tests/unit/haas_server/test_app.py) | 全実行 | 変更 | ✅ | `テスト結果/20261108061111_1d8c0dd_単体テスト.log` |
| [tests/unit/haas_server/test_main.py](https://github.com/shuhei1101/voice-paste/blob/1d8c0dd/tests/unit/haas_server/test_main.py) | 全実行 | 変更 | ✅ | `テスト結果/20261108061111_1d8c0dd_単体テスト.log` |

### ドキュメント修正

利用者向けの使い方『起動と設定』の修正だけで、規約『V字モデル』の対応表で対応する単体・結合テストが無いため、テストを実行していない。

### 結合

develop の取り込みの後に全件（`tests/integration`）を実行し、766 passed・1 skipped。下の表は今回変えた・関係するファイル。lint は `テスト結果/20261108061111_1d8c0dd_lint.log`（全て exit 0）。

| ファイル | メソッド | 変更種別 | 結果 | 補足 |
| --- | --- | --- | --- | --- |
| [tests/integration/haas_server/test_transcribe.py](https://github.com/shuhei1101/voice-paste/blob/1d8c0dd/tests/integration/haas_server/test_transcribe.py) | `test_normal_when_tuning_values`・`test_error_when_tuning_value_invalid` | 変更 | ✅ | 新規追加テスト。既存のテストは偽のモデルの引数（options・alpha）の追従<br>`テスト結果/20261108061111_1d8c0dd_結合テスト.log` |
| [tests/integration/haas_server/test_health.py](https://github.com/shuhei1101/voice-paste/blob/1d8c0dd/tests/integration/haas_server/test_health.py) | `test_normal` | 変更 | ✅ | 応答に dtype・device を追加<br>`テスト結果/20261108061111_1d8c0dd_結合テスト.log` |
| [tests/integration/haas_server/test_shutdown.py](https://github.com/shuhei1101/voice-paste/blob/1d8c0dd/tests/integration/haas_server/test_shutdown.py) | 全実行 | 実行のみ | ✅ | 偽のサーバー（fake_server.py）の引数の追従の回帰確認<br>`テスト結果/20261108061111_1d8c0dd_結合テスト.log` |
