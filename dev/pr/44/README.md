# AI チャットの送り先をカスタムプリセットにし、エンドポイントへ送る種類を足す

## 概要

録音の画面の AI チャットの送り先を、ユーザーが自由に足し・消しできるカスタムプリセットに置き換え、プリセットの種類に「ブラウザで開く」と「エンドポイントへ送る」を持たせる。
起こした文字を、設定で指定したエンドポイント（HTTP）へ送れるようになる。

## 背景

[Issue #35](https://github.com/shuhei1101/voice-paste/issues/35) の要望。
元の要望は close 済みの [#5](https://github.com/shuhei1101/voice-paste/issues/5)（ボタンで API のエンドポイントへ送る）で、作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の [リスクと移行計画](https://github.com/shuhei1101/voice-paste/blob/develop/dev/pr/12/%E6%96%B9%E9%87%9D%E6%B1%BA%E3%82%81/5_%E3%83%AA%E3%82%B9%E3%82%AF%E3%81%A8%E7%A7%BB%E8%A1%8C%E8%A8%88%E7%94%BB.md)）で、移行が終わった後に出力先として足すと決めてある。
出力先を一覧に登録する形は [#20](https://github.com/shuhei1101/voice-paste/issues/20)（[#34](https://github.com/shuhei1101/voice-paste/pull/34)）で作った。
今ある呼び出し元へ返す出力先（`callback`）は API から始めた録音の返送先へ返すだけで、ホットキー・トレイから始めた録音を設定のエンドポイントへ送るものではない。
送り先を複数持ち、送り先ごとのボタン・ホットキーで送る部分は、[#35 の確認事項](https://github.com/shuhei1101/voice-paste/issues/35#issuecomment-5945453020) の回答で [#40](https://github.com/shuhei1101/voice-paste/issues/40) へ分けたが、[PR の確認事項](https://github.com/shuhei1101/voice-paste/pull/44#discussion_r4172598315) の回答で、AI チャットの送り先とまとめたカスタムプリセットとしてこの PR で受けることになった。

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
- [x] ~~PoC 検証~~（JSON を httpx で POST するのは呼び出し元へ返す出力先（[#33](https://github.com/shuhei1101/voice-paste/pull/33)）で実装済みで、未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 声で入力した文字を貼り付ける は「設定でオンにした出力先」で書いてあり、出力先の種類を並べていない）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] 単一ユースケース設計
- [ ] モック作成（設定画面のカスタムプリセットの一覧・録音の画面のプリセットのボタンの並び）
- [ ] インターフェース定義設計
- [x] ~~部品設計~~（部品設計を持たないプロジェクトで、部品を作らない）
- [ ] 画面設計
- [ ] モジュール構成設計
- [ ] ドキュメント修正（docs/使い方/録音して貼り付ける.md）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成