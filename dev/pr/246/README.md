# 常駐アプリの設定を、既定値・環境の値・checkout の上書きの 3 レイヤーへ合わせる

## 概要

常駐アプリの設定を、既定値 `config/defaults.yaml` → 環境の値 `settings.yaml` → checkout の上書き `settings.local.yaml` の 3 レイヤーで読むようにする。

## 背景

[Issue #236](https://github.com/shuhei1101/voice-paste/issues/236) の要望。
[PR #235](https://github.com/shuhei1101/voice-paste/pull/235)（[#216](https://github.com/shuhei1101/voice-paste/issues/216) AI Monitor v0.3.0 の配布物への追従）のドキュメント修正で、判定フローチャート『設定値の置き場所』と外部規約『シークレットと環境変数』に常駐アプリの設定が合っていないことが分かり、[implementer の完了報告](https://github.com/shuhei1101/voice-paste/pull/235#discussion_r4431599791) の案で切り出した。
今は既定値を pydantic のモデル（`_item(...)` の既定値と `OS_DEFAULT_OVERRIDES`）が持ち、ユーザーの値を platformdirs のフォルダの `settings.toml` に置いて tomlkit で読み書きしている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの設定の読み書きと置き場所の計画書 |
| [確認ログ](./確認ログ.md) | ユーザーへの確認事項の決着 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] PoC 検証
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースの流れを変えない）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] 単一ユースケース設計
- [x] ~~モック作成~~（画面の要素と見た目を変えない。変わるのは設定ファイルの名前と置き場所の記述）
- [x] インターフェース定義設計
- [x] ~~部品設計~~（部品を変えない）
- [x] 画面設計
- [x] モジュール構成設計
- [x] ドキュメント修正
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
