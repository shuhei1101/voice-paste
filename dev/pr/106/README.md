# E2E のキー送りの差し替えが Enter の修飾キーを受けるようにする

## 概要

E2E が常駐アプリへ差し込むキー送りの差し替え（`KeyLog.send_enter`）が Enter の修飾キーの並びを受けるようにし、release/v0.5.0 の E2E を pass させる。

## 背景

[Issue #104](https://github.com/shuhei1101/voice-paste/issues/104) の E2E 失敗。
release PR [#102](https://github.com/shuhei1101/voice-paste/pull/102)（Sprint v0.5.0 の E2E、[#93](https://github.com/shuhei1101/voice-paste/issues/93)）の [実行の結果](https://github.com/shuhei1101/voice-paste/pull/102#discussion_r4269366777) で、`tests/e2e/複合ユースケース/test_paste_voice_text.py::test_normal` が fail した（`KeyLog(pasted=['<ctrl>+v'], enters=0).enters` が 1 にならない）。

- [#91](https://github.com/shuhei1101/voice-paste/pull/91) で `send_enter` が修飾キーの並びを受けるようになり、貼り付けて送信は `send_enter(get_enter_modifiers())` と呼ぶ
- `tests/support/inprocess.py` の `KeyLog.send_enter(self)` が引数を受けず、呼び出しが `TypeError` になって Enter が控えられない（切り分け: テスト不備）
- 単体テストと結合テストは修飾キーつきの呼び出しを確かめており、製品のコードは設計書どおり

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリ（複合ユースケースの E2E とその支えのコード）の計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: シナリオは変わらず、E2E の支えのコードを実装に追従させるだけ）
- [x] ~~デザインスタイル選定~~（画面を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] ~~単一ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~モック作成~~（画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: インターフェースを変えない）
- [x] ~~部品設計~~（画面を変えない）
- [x] ~~画面設計~~（画面を変えない）
- [x] ~~モジュール構成設計~~（影響なし: 常駐アプリのクラス・関数を変えない）
- [x] ~~ドキュメント修正~~（更新するドキュメントが無い）
- [x] ~~単体テスト作成~~（常駐アプリの関数を変えない）
- [x] ~~実装~~（常駐アプリを変えない。直すのは E2E の支えのコードで、E2E テスト作成で扱う）
- [x] ~~結合テスト作成~~（インターフェース定義と画面設計を変えない）
- [ ] E2E テスト作成
