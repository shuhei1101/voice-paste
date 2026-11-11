# Haas の文字起こしのサーバー

## 現状

<!-- table: data -->

| 分類 | ページ / ファイル | 概要 | 補足 |
| --- | --- | --- | --- |
| ドキュメント | [docs/interface/](https://github.com/shuhei1101/voice-paste/blob/22c4ca60f1ab10a81e760954efc127c1b4fac1ed/docs/interface/) | Haas の文字起こしのサーバーの API（IF-12〜IF-14） | 全件が本文に Mermaid の図を持つ |
| ドキュメント | [docs/module/](https://github.com/shuhei1101/voice-paste/blob/22c4ca60f1ab10a81e760954efc127c1b4fac1ed/docs/module/) | `haas_server/` のモジュールと分類 | タグ・`description` を持たない |

<!-- /table -->

## 変更方針

| 対象 | 方針 | 補足 |
| --- | --- | --- |
| 文書 | [常駐アプリ](./常駐アプリ.md) の変更方針と同じ方針で、図・表・文・タグ・description・エイリアスと用語・関連を再設定する | 関連のコードの行は `haas_server/` を対象にする |
| 既存機能への影響 | `haas_server/`・`tests/` は変えない | - |

## テスト結果

`haas_server/`・`tests/` を変えないため、関係する単体・結合テストは無い。
