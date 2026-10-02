# 出力先を一覧に登録する形で作り直す

## 概要

貼り付けて送信・貼り付けのみ・コピーのみ・AI チャットへ送るの各出力先を、`features/outputs` の一覧に登録する形で新しい構成に作る。
各出力先を設定でオン・オフでき、出力先を足すときに既存のモジュールで変えるのが一覧への登録の 1 か所で済むようにする。

## 背景

[Issue #20](https://github.com/shuhei1101/voice-paste/issues/20) の要望。
作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の `dev/pr/12/方針決め/`）の目的 2 で、移行の Issue の並びの順 7 にあたる。
今の `voice_paste_legacy` は届け方を 1 つ足すのに画面と流れの 4 か所を直し、AI チャットへ送る届け方を文字列の取り決めで渡している（方針の記録のリスクと対策）。
出力先の型・一覧・`deliver` と呼び出し元へ返す出力先は [#19](https://github.com/shuhei1101/voice-paste/issues/19)（[#33](https://github.com/shuhei1101/voice-paste/pull/33)）で置いてあり、一覧には呼び出し元へ返す 1 行だけが登録されている。
出力先の設定（`outputs[]`）は [#16](https://github.com/shuhei1101/voice-paste/issues/16)（[#28](https://github.com/shuhei1101/voice-paste/pull/28)）で実装済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] ~~PoC 検証~~（pyperclip・pynput・Microsoft Edge の `--app` は `voice_paste_legacy` で普段使いしており、未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 声で入力した文字を貼り付ける は [#26](https://github.com/shuhei1101/voice-paste/pull/26) で作り直し後の形に起こしてあり、そのままで要件を満たす）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [x] ~~単一ユースケース設計~~（影響なし: 起こした文字を届ける は [#26](https://github.com/shuhei1101/voice-paste/pull/26) で 4 つの出力先を作り直し後の形に起こしてあり、そのままで要件を満たす）
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [x] ~~インターフェース定義設計~~（影響なし: 出力先は外部のインターフェースを持たず、呼び出し元へ返すは [#33](https://github.com/shuhei1101/voice-paste/pull/33) で作ってある）
- [x] ~~部品設計~~（画面を作らない）
- [x] ~~画面設計~~（画面を作らない。確定の操作で出力先を選ぶ画面は [#21](https://github.com/shuhei1101/voice-paste/issues/21)）
- [x] モジュール構成設計
- [x] ~~ドキュメント修正~~（更新ドキュメントが無い）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [x] ~~E2E テスト作成~~（ホットキー・トレイから始めた録音が新しい構成にまだ無く、選んだ出力先へ届ける流れを実機で通せない。E2E は [#21](https://github.com/shuhei1101/voice-paste/issues/21) で作る）