# 作り直しのあるべき姿の設計書を起こす

## 概要

作り直しの方針に沿って、ほかのシステムが API で録音を開始・停止・完了でき、ホットキーで録って貼り付ける今の使い方も新しい構成の上で動く、あるべき姿の設計書（シナリオ・アーキテクチャ図・非機能要件・モジュール構成・インターフェース定義）を起こす。

## 背景

[Issue #14](https://github.com/shuhei1101/voice-paste/issues/14) の要望。
[#11](https://github.com/shuhei1101/voice-paste/issues/11)（作業 PR [#12](https://github.com/shuhei1101/voice-paste/pull/12)）の方針決めで作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)）が決まり、この Issue は移行の Issue の並びの順 1 にあたる。
後続の移行の Issue（[#15](https://github.com/shuhei1101/voice-paste/issues/15)〜[#23](https://github.com/shuhei1101/voice-paste/issues/23)）は、ここで起こす設計書を作り直しの正本にして進める。
今の設計書は [#10](https://github.com/shuhei1101/voice-paste/pull/10) の RE で今の振る舞いを写したもので、あるべき姿は含まない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
| [文字起こしワーカー](./文字起こしワーカー.md) | 文字起こしワーカーの計画書 |
| [確認ログ](./確認ログ.md) | ユーザーへの確認事項の決着 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] ~~PoC 検証~~（設計書だけを起こし、コードを変えない）
- [x] 複合ユースケース設計
- [x] ~~デザインスタイル選定~~（画面の構成と見た目は [#21](https://github.com/shuhei1101/voice-paste/issues/21) のデザインの工程で決める）
- [x] ~~画面一覧・画面遷移~~（画面の構成と見た目は [#21](https://github.com/shuhei1101/voice-paste/issues/21) のデザインの工程で決める）
- [x] 単一ユースケース設計
- [x] ~~モック作成~~（画面の構成と見た目は [#21](https://github.com/shuhei1101/voice-paste/issues/21) のデザインの工程で決める）
- [x] インターフェース定義設計
- [x] ~~部品設計~~（画面の構成と見た目は [#21](https://github.com/shuhei1101/voice-paste/issues/21) のデザインの工程で決める）
- [x] ~~画面設計~~（画面の構成と見た目は [#21](https://github.com/shuhei1101/voice-paste/issues/21) のデザインの工程で決める）
- [x] モジュール構成設計
- [x] ドキュメント修正（設計書/index.yaml）
- [x] ~~単体テスト作成~~（コードを変えない）
- [x] ~~実装~~（コードを変えない）
- [x] ~~結合テスト作成~~（コードを変えない）
- [x] ~~E2E テスト作成~~（コードを変えない）