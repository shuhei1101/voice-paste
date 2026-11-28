# 開発ドキュメントのサイドバーで、入れ子にすべきグループを入れ子にする

## 概要

開発ドキュメントサーバーで配信元 `voice-input` を開いた人が、サイドバーの入れ子のグループから設計書とコードを探せるようにする。

## 背景

[Issue #349](https://github.com/shuhei1101/voice-paste/issues/349) の要望。
project-index の `nav` の `group` は、子の `items[]` に `group` を持てる（入れ子にできる）ようになった。
この配信元の `project-index.yaml` の `nav` は、[#324](https://github.com/shuhei1101/voice-paste/issues/324)（[#327](https://github.com/shuhei1101/voice-paste/pull/327)）で定義したグループが 1 段だけで、入れ子を使っていない。
設定ファイルの名前は [#348](https://github.com/shuhei1101/voice-paste/issues/348)（[#350](https://github.com/shuhei1101/voice-paste/pull/350)）で `dev-docs.yaml` から `project-index.yaml` へ改名済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |

## 実装

`project-index.yaml` の `nav` で、設計書とコードのタブのグループの中に、機能か利用者の作業の単位のグループを 1 段入れた（入れ子は 2 階層まで）。

| タブ | グループ | 分けた軸 | 入れ子のグループ |
| --- | --- | --- | --- |
| 設計書 | シナリオ | 主アクター（利用者の作業） | 常駐アプリで使用する・ほかのシステムから使用する・外の端末のブラウザから使用する |
| 設計書 | インターフェース定義 | 入口になる機能 | 録音の API・常駐アプリの出力先・ブラウザの文字起こし・Haas の文字起こしのサーバー・テスト |
| 設計書 | モジュール構成 | 機能（モジュール名の 2 番目の区切り。文字起こしワーカー・Haas の文字起こしのサーバーはサブシステム） | 起動と配線・録音セッション・録音・文字起こし・文字起こしワーカー・Haas の文字起こしのサーバー・補正・出力先・履歴・ブラウザの文字起こし・APIサーバー・ホットキーと画面・外部連携・共通 |
| 設計書 | データ | 保存する場所のサブシステム | 常駐アプリ・外の端末のブラウザ・Haas の文字起こしのサーバー |
| 設計書 | 外部ライブラリ | 使用するサブシステム（`used_in`） | 常駐アプリ・Haas の文字起こしのサーバー・開発とテスト |
| コード | 常駐アプリ | パッケージのフォルダ（`auto.filter` の `path` の `prefix`） | features/・integrations/・runtime/・ui/・server/・shared/ |
| コード | テスト | テストの層のフォルダ | unit/・integration/・e2e/・nfr/・external/・support/・mocks/ |

1 件だけのグループ（アーキテクチャ図・非機能要件・設定・フォルダ構成・開発コマンド・テスト実行方法）と、件数の少ないグループ（画面設計・ER 図・外部API・Haas の文字起こしのサーバーのコード）は分けない。
これまで `auto` で末尾に並んでいた文書（SC-14・SC-15・MOD-105・LIB-39）も、入れ子のグループの中に配置した。

### 画面確認

作業ブランチの `nav` を重ねた設定で project-index（ポート 18786）と dev-docs（ポート 18787）を起動し、`rev=docs/dev-docs/nest-sidebar-groups` の画面を撮った。
開いている文書のグループが入れ子で開き、ほかのグループは閉じて並ぶ。

| 場面 | 画面幅 | スクリーンショット |
| --- | --- | --- |
| 設計書 > モジュール構成 > 録音セッション | 1280x800 | [1-design-module_1280x800.png](./画像/1-design-module_1280x800.png) |
| 設計書 > モジュール構成 > 録音セッション | 768x1024 | [1-design-module_768x1024.png](./画像/1-design-module_768x1024.png) |
| 設計書 > シナリオ > 常駐アプリで使用する | 1280x800 | [2-design-scenario_1280x800.png](./画像/2-design-scenario_1280x800.png) |
| 設計書 > インターフェース定義 > 常駐アプリの出力先 | 1280x800 | [3-design-interface_1280x800.png](./画像/3-design-interface_1280x800.png) |
| 設計書 > データ > 外の端末のブラウザ | 1280x800 | [4-design-data_1280x800.png](./画像/4-design-data_1280x800.png) |
| 設計書 > 外部ライブラリ > Haas の文字起こしのサーバー | 1280x800 | [5-design-library_1280x800.png](./画像/5-design-library_1280x800.png) |
| コード > 常駐アプリ > features/ | 1280x800 | [6-code_1280x800.png](./画像/6-code_1280x800.png) |

## テスト結果

単体・結合テストは無し。変更は開発ドキュメントの配信の設定だけで、`tests/`・`src/`・`haas_server/` のどのファイルも `project-index.yaml` を参照しないため（`judge_integration_scope` の判定は R7 で、参照するテストは無かった）。
