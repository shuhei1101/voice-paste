# Ubuntu の Wayland のセッションでも、ホットキーと貼り付けが働くようにする

## 概要

ユーザーが Ubuntu の Wayland のセッションでも、ホットキーで録音を始め、起こした文字をアクティブなアプリへ貼り付けられるようにする。

## 背景

[Issue #200](https://github.com/shuhei1101/voice-paste/issues/200) の要望。
Linux 対応（[#196](https://github.com/shuhei1101/voice-paste/issues/196)〜[#199](https://github.com/shuhei1101/voice-paste/issues/199)）は Ubuntu 24.04 の Xorg のセッションを対象にしていて、`docs/使い方/起動と設定.md` も「Wayland のセッションは対象外」と記載している。
ホットキーの受付とキーの送信は pynput の Xorg のバックエンドで、端末アプリの見分けは python-xlib で行うため、Wayland ではネイティブの Wayland のアプリとの間で働かない。
Ubuntu 24.04 は Wayland が既定で、Ubuntu 25.10 では GNOME の Xorg のセッションが無くなった。
24.04 の GNOME（46）の portal には GlobalShortcuts が無い（[受付の判断](https://github.com/shuhei1101/voice-paste/issues/200#issuecomment-6456357214)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（セッションの種類の判定・Wayland のホットキー・キーの送信・クリップボード・画面・通しの確認） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [ ] PoC 検証
- [x] ~~複合ユースケース設計~~（影響なし: 声で入力した文字を貼り付ける流れを変えない）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目が変わらない）
- [x] ~~画面一覧・画面遷移~~（利用者に見える画面の見た目が変わらない）
- [ ] 単一ユースケース設計
- [x] ~~モック作成~~（利用者に見える画面の見た目が変わらない）
- [ ] インターフェース定義設計
- [x] ~~部品設計~~（部品を変えない）
- [x] ~~画面設計~~（変更が画面に及ばない）
- [ ] モジュール構成設計
- [ ] ドキュメント修正
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
