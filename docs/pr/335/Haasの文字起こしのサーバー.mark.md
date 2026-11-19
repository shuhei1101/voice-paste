# Haas の文字起こしのサーバー

## 現状

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/module/MOD-99.py.yaml](https://github.com/shuhei1101/voice-paste/blob/develop/docs/module/MOD-99.py.yaml) | Haas の文字起こしのサーバーのモジュール構成 | 文字列の refs を持つ |
| ドキュメント | [docs/module/MOD-100.py.yaml](https://github.com/shuhei1101/voice-paste/blob/develop/docs/module/MOD-100.py.yaml) | Haas の文字起こしのサーバーのモジュール構成 | 文字列の refs を持つ |
| ドキュメント | [docs/module/MOD-101.py.yaml](https://github.com/shuhei1101/voice-paste/blob/develop/docs/module/MOD-101.py.yaml) | Haas の文字起こしのサーバーのモジュール構成 | 文字列の refs を持つ |

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| 設計書の refs | [常駐アプリ](./常駐アプリ.mark.md) の `## 変更方針` の「設計書の refs の `to`・`item`」「設計書の refs の `type`」「設計書の refs の `when`」と同じ方法で関連の要素へ移す | 関連先は変えない |

## テスト結果

単体・結合テストは実行しない。変更は設計書のメタデータだけで、コードを変えない。

代わりに、作業ブランチ（`37a8b68`）で `design_docs validate` と `design_docs publish` を実行し、どちらも終了の状態 0 で終わることを確かめた（ログは [常駐アプリ](./常駐アプリ.mark.md) の `## テスト結果`）。
