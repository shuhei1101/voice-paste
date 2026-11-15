# Haas の文字起こしのサーバー

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/module/MOD-98.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/module/MOD-98.yaml)・[MOD-99.py.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/module/MOD-99.py.yaml)・[MOD-100.py.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/module/MOD-100.py.yaml)・[MOD-101.py.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/module/MOD-101.py.yaml) | Haas の文字起こしのサーバーのモジュール構成 4 件 | `tags`・`aliases`・`lead` なし |
| ドキュメント | [docs/interface/IF-12.py.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/interface/IF-12.py.yaml)・[IF-13.py.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/interface/IF-13.py.yaml)・[IF-14.py.yaml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/docs/interface/IF-14.py.yaml) | 音声を文字に起こす・準備できたかを返す・停止する | `tags`・`aliases` なし。`lead` あり |
| 管理用の YAML | [haas_server/src/files.yml](https://github.com/shuhei1101/voice-paste/blob/f8bc5ed06f2c314dd457cfa2c86216a05de0b36b/haas_server/src/files.yml) | コード 3 行 | `related` だけを持つ |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| メタデータ | 常駐アプリの計画書の変更方針と同じ方針で、`tags`（`main: true` を含む）・`aliases`・`lead` と、`files.yml` の行の `tags`・`description` を記載する | - |

## テスト結果

### 単体

なし（コードを変えない）

### 結合

なし（コードを変えない）
