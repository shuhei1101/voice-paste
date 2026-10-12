# 用語集を設定画面で編集し、プリセットで切り替えて行ごとにオン・オフできるようにする

## 概要

ユーザーが設定画面から用語集の行（誤変換と正しい表記）を足す・書き換える・消すことができ、用語集をプリセットとして複数持って切り替え、行ごとにオン・オフできるようにする。

## 背景

[Issue #87](https://github.com/shuhei1101/voice-paste/issues/87) の要望。
今の用語集は `glossary_path` の CSV 1 つで、中身を変えるにはファイルを直接書き換える。
develop の設定画面（[settings_window.py](https://github.com/shuhei1101/voice-paste/blob/develop/src/voice_paste/ui/windows/settings_window.py) の `_add_glossary`）は CSV の場所を選ぶだけで、補正（[correction/service.py](https://github.com/shuhei1101/voice-paste/blob/develop/src/voice_paste/features/correction/service.py)）は読む関数と置き換える関数だけを持ち、プリセットも行ごとのオン・オフも無い。
用語集以外の設定の GUI 化は [#88](https://github.com/shuhei1101/voice-paste/issues/88) で扱う。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理・影響する UC 一覧・更新ドキュメント・スコープ外 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |

## タスク一覧

- [x] ~~初期構築~~（[#8](https://github.com/shuhei1101/voice-paste/pull/8) で済んでいる）
- [x] ~~リバースエンジニアリング~~（[#10](https://github.com/shuhei1101/voice-paste/pull/10) で現状の設計書が揃っている）
- [x] ~~方針決め~~（方針決めを依頼する Issue ではない）
- [x] ~~PoC 検証~~（行の一覧の編集は設定画面の出力先のプリセットの一覧と同じ PySide6 の部品で組め、CSV の読み書きは標準の csv で、未検証の技術機構に依存しない）
- [x] ~~複合ユースケース設計~~（影響なし: 補正の流れは変わらず、補正に使う行が変わるだけ）
- [x] ~~デザインスタイル選定~~（デザイン方針があり、見た目の方向を変えない）
- [x] ~~画面一覧・画面遷移~~（設定画面の「文字起こし（用語集）」のまとまりへの足し込みで、画面の追加・削除と画面遷移の変更を含まない）
- [x] 単一ユースケース設計
- [ ] モック作成
- [x] ~~インターフェース定義設計~~（API の入出力を変えない）
- [x] ~~部品設計~~（部品設計を持たないプロジェクトで、部品を作らない）
- [ ] 画面設計
- [ ] モジュール構成設計
- [ ] ドキュメント修正（docs/使い方/録音して貼り付ける.md）
- [ ] 単体テスト作成
- [ ] 実装
- [ ] 結合テスト作成
- [ ] E2E テスト作成
