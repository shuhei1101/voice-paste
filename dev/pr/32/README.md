# 録音とシステム音量の操作を新しい構成で作り直す

## 概要

録音（開始・一時停止・再開・確定・取り消し）と録音中のシステム音量の下げ戻しを `src/voice_paste/` の新しい構成で作り直し、pycaw の版が上がって API が変わったら音量のアダプタの契約テストで気づけるようにする。

## 背景

[Issue #18](https://github.com/shuhei1101/voice-paste/issues/18) の要望。
作り直しの方針（[#13](https://github.com/shuhei1101/voice-paste/issues/13)、記録は [#12](https://github.com/shuhei1101/voice-paste/pull/12) の `dev/pr/12/方針決め/`）の移行の Issue の並びの順 5 にあたる。
土台（`src/voice_paste/` のレイアウト・設定のモデル・ログ・例外・import-linter）は [#16](https://github.com/shuhei1101/voice-paste/issues/16)（[#28](https://github.com/shuhei1101/voice-paste/pull/28)）で、録音を受け取る `Recording` と履歴は [#17](https://github.com/shuhei1101/voice-paste/issues/17)（[#31](https://github.com/shuhei1101/voice-paste/pull/31)）で置いてある。
あるべき姿の録音と音量のアダプタのモジュール構成は [#14](https://github.com/shuhei1101/voice-paste/issues/14)（[#26](https://github.com/shuhei1101/voice-paste/pull/26)）で `status: planned` として起こしてある。
今の `voice_paste_legacy` は、マイクを開けないと音量が下がったまま残り、pycaw の版の上げで音量の下げ戻しが動かなくなっても気づく手段が無い（方針の記録のリスクと対策）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・反映作業・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない。方針は [#13](https://github.com/shuhei1101/voice-paste/issues/13) で決まっている）
- [x] ~~PoC 検証~~（sounddevice の録音と pycaw の音量の操作は `voice_paste_legacy` で動いている形を移すもので、未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 録音の流れをつなぐのは [#19](https://github.com/shuhei1101/voice-paste/issues/19)）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [x] ~~単一ユースケース設計~~（影響なし: 録音する のシナリオは [#26](https://github.com/shuhei1101/voice-paste/pull/26) で作り直し後の形に起こしてあり、振る舞いを変えない）
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [x] ~~インターフェース定義設計~~（API・入口を作らない。API は [#19](https://github.com/shuhei1101/voice-paste/issues/19) で作る）
- [x] ~~部品設計~~（画面を作らない）
- [x] ~~画面設計~~（画面を作らない。録音の画面と波形は [#21](https://github.com/shuhei1101/voice-paste/issues/21)）
- [x] モジュール構成設計
- [x] ドキュメント修正（設計書/テスト/テスト実行方法・設計書/非機能要件・設計書/外部ライブラリ。pycaw・comtypes の動作確認は契約テストを実機で通した結果で書くため、結合テスト作成で書き換える）
- [x] 単体テスト作成
- [x] 実装
- [ ] 結合テスト作成
- [x] ~~E2E テスト作成~~（利用者の操作の流れが変わらず、対象のシナリオが `tests/e2e/` のテストファイルを持たない）