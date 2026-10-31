# Linux（Ubuntu）の不具合 4 件を修正する（トレイのアイコン・設定画面の一覧の幅・evdev のビルドの前提・Wayland の端末アプリへの貼り付けのキー）

## 概要

ユーザーが Ubuntu 24.04 で、初回の起動でもトレイのアイコンを見られ、設定画面の左の一覧を横にスクロールせずに読め、環境構築の手順どおりに依存を入れられ、Wayland のセッションでも端末アプリへ貼り付けられるようにする。

## 背景

[#237](https://github.com/shuhei1101/voice-paste/issues/237) の要望。Linux 対応（[#199](https://github.com/shuhei1101/voice-paste/issues/199)・[#200](https://github.com/shuhei1101/voice-paste/issues/200)）の PoC とレビューで見つかった、次の 4 件の不具合を束ねて修正する。

- [#217](https://github.com/shuhei1101/voice-paste/issues/217): faster-whisper のモデルを取得する初回の起動で、トレイのアイコンが上のバーに出ない（[#214](https://github.com/shuhei1101/voice-paste/pull/214) でスコープ外にし、使い方『起動と設定.md』に起動し直す回避だけを記載した）
- [#218](https://github.com/shuhei1101/voice-paste/issues/218): 設定画面の左の一覧（`group_menu`）は幅を固定の 160px にしていて、Linux では「エンドポイントへ送信」の末尾が切れて横のスクロールバーが出る
- [#222](https://github.com/shuhei1101/voice-paste/issues/222): `pynput` の Linux での依存 `evdev` は PyPI に sdist しか無く、導入時のビルドに要る `gcc` と `linux-libc-dev` が環境構築の手順に無い（[#220](https://github.com/shuhei1101/voice-paste/pull/220) のレビューで見つかった）
- [#223](https://github.com/shuhei1101/voice-paste/issues/223): Wayland のセッションの貼り付け（[#220](https://github.com/shuhei1101/voice-paste/pull/220)）は、GNOME にアクティブなウィンドウを読む標準のインターフェースが無いため、端末アプリでも設定の貼り付けのキーを送信する（[#220](https://github.com/shuhei1101/voice-paste/pull/220) の確認ログでスコープ外にした）

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（トレイを出す時点・設定画面の一覧の幅・環境構築の前提・Wayland の端末アプリの見分け） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [ ] PoC 検証
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースの流れを変えない）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [ ] 単一ユースケース設計
- [x] ~~モック作成~~（一覧の幅の決め方が Issue で決まっていて、designer が決める余地が無い）
- [x] ~~インターフェース定義設計~~（API の入出力と処理フローを変えない）
- [x] ~~部品設計~~（部品を変えない）
- [ ] 画面設計
- [ ] モジュール構成設計
- [ ] ドキュメント修正（使い方/起動と設定.md・使い方/録音して貼り付ける.md・設計書/設定/常駐アプリ.yaml・設計書/開発コマンド/開発コマンド.yaml・設計書/非機能要件/非機能要件.yaml）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
