# 非機能要件テストと release の E2E の実行を Linux（Ubuntu 24.04 の Xorg）でも行えるようにする

## 概要

開発者が非機能要件テストを Linux（Ubuntu 24.04 の Xorg のセッション）でも実行でき、tester がスプリントの release の E2E の実行で検証環境の VM `voice-paste-ubuntu` でも E2E を全件流せるようにする。

## 背景

[Issue #250](https://github.com/shuhei1101/voice-paste/issues/250) の要望で、[#243](https://github.com/shuhei1101/voice-paste/issues/243) と [#244](https://github.com/shuhei1101/voice-paste/issues/244) を束ねる。
[#241](https://github.com/shuhei1101/voice-paste/pull/241)（起点 [#219](https://github.com/shuhei1101/voice-paste/issues/219)）で、Linux の Xorg のセッションで `--run-e2e` を付けた pytest の 1 コマンドで E2E を流せるようにし、録音の入力の WAV を Linux では Open JTalk で書き出すようにした。
非機能要件テストと release の E2E の実行の手順は、#241 のスコープ外にした。
非機能要件テストには、Windows の音声合成（SAPI）を前提に Linux で skip するものと、Windows の NVIDIA GPU を前提に skip するものがあり、検証環境の VM には GPU が無い（[#203](https://github.com/shuhei1101/voice-paste/issues/203)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの非機能要件テストと release の E2E の実行の計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] PoC 検証
- [x] ~~複合ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~デザインスタイル選定~~（利用者に見える画面を変えない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面を変えない）
- [x] ~~単一ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~モック作成~~（利用者に見える画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API を変えない）
- [x] ~~部品設計~~（部品を変えない）
- [x] ~~画面設計~~（変更が画面に及ばない）
- [x] ~~モジュール構成設計~~（影響なし: `src/` を変えない）
- [x] ドキュメント修正
- [x] ~~単体テスト作成~~（`src/` を変えない）
- [x] ~~実装~~（`src/` を変えない。変更は `tests/` に閉じ、E2E テスト作成で行う）
- [x] ~~結合テスト作成~~（`src/` を変えない）
- [ ] E2E テスト作成
