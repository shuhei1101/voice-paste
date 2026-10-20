# .gitattributes で改行コードを決め、Windows と WSL の git で作業ツリーに改行コードだけの差が出ないようにする

## 概要

改行コードの扱いをリポジトリの `.gitattributes` で決め、普段使いのクローンの作業ツリーに改行コードだけの差が出ないようにする。

## 背景

[Issue #119](https://github.com/shuhei1101/voice-paste/issues/119) の不具合。
v0.5.2 のリリース（[#115](https://github.com/shuhei1101/voice-paste/issues/115) / [#117](https://github.com/shuhei1101/voice-paste/pull/117)）の後、普段使いのクローン（メインリポジトリの master）の作業ツリーに改行コードだけの差が残り、`origin/master` への fast-forward と反映作業「普段使いの環境の作り直し」（[#114](https://github.com/shuhei1101/voice-paste/pull/114)）が止まった（[operator の報告](https://github.com/shuhei1101/voice-paste/issues/115#issuecomment-6228861440)）。
同じ作業ツリーを Windows の git（システムの設定で `core.autocrlf=true`）と WSL の git（`core.autocrlf` 未設定）の両方が触り、リポジトリに `.gitattributes` が無いため、Windows の git が CRLF で書き出したファイルを WSL の git が変更として扱う。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [反映作業](./反映作業/index.yaml) | master へ入った後の普段使いのクローンの作業ツリーの書き出し直し |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（未検証の技術機構に依存しない。`.gitattributes` の振る舞いは使い捨てのリポジトリで確かめた）
- [x] ~~複合ユースケース設計~~（影響なし: アプリの振る舞いを変えない）
- [x] ~~デザインスタイル選定~~（画面を変えない）
- [x] ~~画面一覧・画面遷移~~（画面を変えない）
- [x] ~~単一ユースケース設計~~（影響なし: アプリの振る舞いを変えない）
- [x] ~~モック作成~~（画面を変えない）
- [x] ~~インターフェース定義設計~~（影響なし: API と JSON Lines の入出力を変えない）
- [x] ~~部品設計~~（画面を変えない）
- [x] ~~画面設計~~（画面を変えない）
- [x] ~~モジュール構成設計~~（影響なし: コードを変えない）
- [x] ~~ドキュメント修正~~（更新ドキュメントが無い）
- [x] ~~単体テスト作成~~（コードを変えない）
- [x] 実装
- [x] ~~結合テスト作成~~（インターフェース定義と画面設計を変えない）
- [x] ~~E2E テスト作成~~（シナリオを変えない）