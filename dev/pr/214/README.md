# Ubuntu の Xorg のセッションで起動から貼り付けまでを通し、Linux の起動の手段と手順を用意する

## 概要

ユーザーが Ubuntu 24.04 の Xorg のセッションで、手順のページを見て環境を作り、起動の手段から常駐アプリを起動して（ログイン時の自動起動を含む）、ホットキーで録音した文字を貼り付けられるようにする。

## 背景

[Issue #199](https://github.com/shuhei1101/voice-paste/issues/199) の要望。
[#196](https://github.com/shuhei1101/voice-paste/issues/196)（[#202](https://github.com/shuhei1101/voice-paste/pull/202)）で Linux で `python -m voice_paste` が起動するようになり、[#198](https://github.com/shuhei1101/voice-paste/issues/198)（[#210](https://github.com/shuhei1101/voice-paste/pull/210)）でキーの表示と既定値を Ubuntu に合わせた。
起動の手段は Windows の `voice-paste.bat` だけで、`docs/使い方/起動と設定.md` も Windows の手順だけを記載している。
Linux ではクリップボードに `xclip`、録音に `libportaudio2`、画面に `libxcb-cursor0`（[#211](https://github.com/shuhei1101/voice-paste/pull/211) の PoC で分かった）が OS のパッケージとして要る。
Ubuntu 24.04 で録音から貼り付けまでを通して動かしたことは無い。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（Linux の起動のスクリプト・自動起動・OS のパッケージ・起動から貼り付けまでの通しの確認） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] PoC 検証
- [x] ~~複合ユースケース設計~~（影響なし: 声で入力した文字を貼り付ける流れを変えない）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [x] 単一ユースケース設計
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [x] ~~インターフェース定義設計~~（影響なし: API を変えない）
- [x] ~~部品設計~~（部品を変えない）
- [x] ~~画面設計~~（変更が画面に及ばない）
- [ ] モジュール構成設計
- [ ] ドキュメント修正
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
