# 画面・トレイ・ホットキーを新しい構成で作り直す

## 概要

録音の画面・文字起こし中の表示・設定画面・トレイのメニュー・ダイアログを PySide6 で、グローバルのホットキーを pynput で新しい構成に作り直す。
ユーザーが designer の画面の設計どおりの画面とトレイから録音し、ホットキーで録って貼り付けられるようにする。

## 背景

[Issue #21](https://github.com/shuhei1101/voice-paste/issues/21) の要望。
作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の `dev/pr/12/方針決め/`）の目的 3 で、移行の Issue の並びの順 8 にあたる。
今の `voice_paste_legacy` は画面の組み立て・ホットキー・モニターの判定が 1 つのファイルにあり、録音の画面の最前面を 1 度当てるだけで表示中に戻らない（[#4](https://github.com/shuhei1101/voice-paste/issues/4)）。
セッションと API は [#19](https://github.com/shuhei1101/voice-paste/issues/19)（[#33](https://github.com/shuhei1101/voice-paste/pull/33)）、出力先は [#20](https://github.com/shuhei1101/voice-paste/issues/20)（[#34](https://github.com/shuhei1101/voice-paste/pull/34)）で新しい構成に作ってあり、ホットキー・トレイ・画面の入口と、画面での知らせ方がこの Issue へ持ち越されている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
| [確認ログ](./確認ログ.md) | ユーザーへの確認事項の決着 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] PoC 検証
- [x] ~~複合ユースケース設計~~（影響なし: 声で入力した文字を貼り付ける は単一ユースケースの箱の連鎖で、画面とホットキーの操作は単一ユースケース側に書く。対応テストファイルとテスト関数は E2E テスト作成で付ける）
- [x] デザインスタイル選定
- [x] 画面一覧・画面遷移
- [x] 単一ユースケース設計
- [x] モック作成
- [x] ~~インターフェース定義設計~~（影響なし: API の入出力は変えず、画面の要素と操作は画面設計に書く）
- [x] ~~部品設計~~（PySide6 の画面で、Storybook のストーリーとして描く部品を持たない。画面ごとの要素は画面設計に書く）
- [ ] 画面設計
- [ ] モジュール構成設計
- [x] ~~ドキュメント修正~~（更新ドキュメントが無い）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成