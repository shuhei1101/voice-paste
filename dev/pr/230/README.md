# E2E・非機能要件テストの補助コードで、貼り付けのキーの送信を PlatformAdapters の項目として差し替える

## 概要

E2E・非機能要件テストの補助コードが、貼り付けのキーの送信を `PlatformAdapters` の項目として差し替え、`start_inprocess_app`・`run_resident_app`（貼り付けのキーの控えを渡すケース）・`test_paste_latency` が起動の時点で fail しないようにする。

## 背景

[Issue #228](https://github.com/shuhei1101/voice-paste/issues/228) の不具合。
[#220](https://github.com/shuhei1101/voice-paste/pull/220) で `src/voice_paste/main.py` が貼り付けのキーの送信を `PlatformAdapters.send_paste` の項目にし、`send_paste` を `select_platform_adapters` の分岐の中で import するようになった。
テストの補助コードは、まだ `monkeypatch.setattr(main_module, "send_paste", ...)` でモジュール直下の名前を差し替えていて、`AttributeError` になる。
このままでは今の Sprint の E2E 実行（[#201](https://github.com/shuhei1101/voice-paste/issues/201)）が通らない。
[PR #227](https://github.com/shuhei1101/voice-paste/pull/227) の E2E テスト作成で implementer が報告した（[完了報告](https://github.com/shuhei1101/voice-paste/pull/227#discussion_r4424150567)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書（テストの補助コードでの貼り付けのキーと Enter の差し替え） |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない。`PlatformAdapters` の項目を `dataclasses.replace` で差し替える形は、同じ補助コードのシステム音量・ブラウザを開く呼び出しで動いている）
- [x] ~~複合ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~デザインスタイル選定~~（利用者に見える画面の見た目を変えない）
- [x] ~~画面一覧・画面遷移~~（画面の追加・削除と画面遷移の変更を含まない）
- [x] ~~単一ユースケース設計~~（影響なし: シナリオを変えない）
- [x] ~~モック作成~~（利用者に見える画面の見た目を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API の入出力を変えない）
- [x] ~~部品設計~~（部品設計を持たないプロジェクトで、部品を作らない）
- [x] ~~画面設計~~（画面の要素と操作を変えない）
- [x] ~~モジュール構成設計~~（影響なし: `src/` を変えない。修正するのはテストの補助コード）
- [x] ~~ドキュメント修正~~（更新ドキュメントなし）
- [x] ~~単体テスト作成~~（単体テストを変えない）
- [x] ~~実装~~（`src/` を変えない。修正するのはテストの補助コードで、E2E テスト作成で扱う）
- [x] ~~結合テスト作成~~（結合テストを変えない）
- [ ] E2E テスト作成
