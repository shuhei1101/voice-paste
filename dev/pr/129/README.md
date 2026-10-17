# 録音の画面の結合テストで、経過の表示を環境の速さに左右されずに確かめる

## 概要

録音の画面の結合テストで経過の表示を確かめる 5 件を、遅い環境でも落ちない確かめ方へ直す。

## 背景

[Issue #110](https://github.com/shuhei1101/voice-paste/issues/110) の不具合。
[PR #108](https://github.com/shuhei1101/voice-paste/pull/108) の結合テスト作成で、implementer が対象外として報告した（[報告](https://github.com/shuhei1101/voice-paste/pull/108#discussion_r4285920124)）。

- `test_head_row_action_does_not_stop_recording` は `QTest.qWait(1200)` の後に経過の表示が「00:01」であることを実時間で比べ、遅い環境では「00:03」になって落ちる
- 同じ形の比較が `test_elapsed_label_when_running`・`test_elapsed_label_when_paused`・`test_hide_button_action_when_paused_while_hidden`・`test_hide_button_action_then_restore` にもある
- 起点 Issue の「続けて回すと遅くなる」報告は [#95](https://github.com/shuhei1101/voice-paste/issues/95) へ移された

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリ（録音の画面と、その結合テスト）の計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] ~~単一ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~モック作成~~（利用者に見える画面の見た目を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API の入出力を変えない）
- [x] ~~部品設計~~（部品設計を持たないプロジェクトで、部品を作らない）
- [x] ~~画面設計~~（画面の要素と操作を変えず、経過時間の仕様も変えない）
- [x] モジュール構成設計
- [x] ~~ドキュメント修正~~（更新ドキュメントなし）
- [x] ~~単体テスト作成~~（`RecordingWindow` の振る舞いは画面の結合テストで確かめ、単体テストを持たない）
- [ ] 実装
- [ ] 結合テスト作成
- [x] ~~E2E テスト作成~~（E2E を変えない）
