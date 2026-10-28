# Linux（Ubuntu）で環境を作って常駐アプリを起動できるようにする

## 概要

ユーザーが Ubuntu で dev の依存を含む環境を作り、常駐アプリを起動できるようにする。
Windows の動きは変えない。

## 背景

[Issue #196](https://github.com/shuhei1101/voice-paste/issues/196) の要望。
Ubuntu 24.04 で `uv sync --frozen` を流すと、dev グループの `pywin32` に Linux の wheel が無く失敗する。
`--no-dev` で入れても、無条件の依存の `comtypes` を import できず、`single_instance.py` は読み込み時に `ctypes.WinDLL` を呼ぶため、常駐アプリが起動しない。
Linux 対応のうち、文字起こしのエンジン（[#197](https://github.com/shuhei1101/voice-paste/issues/197)）・キーの表示と既定値（[#198](https://github.com/shuhei1101/voice-paste/issues/198)）・起動の手段と手順（[#199](https://github.com/shuhei1101/voice-paste/issues/199)）・Wayland（[#200](https://github.com/shuhei1101/voice-paste/issues/200)）は別の Issue で扱い、#198〜#200 はこの PR を前提にする。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（依存の宣言・OS ごとの実装の選択・単一インスタンス・音量・ブラウザ・設定の既定値） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない。Linux の排他はロックファイルの `fcntl.flock` と Unix ドメインソケットで、検証環境の VM で実装の工程に確かめる）
- [x] ~~複合ユースケース設計~~（影響なし: 複合ユースケースの流れを変えない）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] 単一ユースケース設計
- [x] ~~モック作成~~（設定画面で Linux のときに音量の項目を出さないことが Issue で決まっており、designer が決める見た目が無い）
- [x] ~~インターフェース定義設計~~（影響なし: API を変えない）
- [x] ~~部品設計~~（部品を変えない）
- [x] 画面設計
- [x] モジュール構成設計
- [x] ドキュメント修正
- [x] 単体テスト作成
- [x] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
