# 画面設計書を design-schemas/v12.0.0 で記載し直し、気づいた設計の漏れを実装とテストまで修正する

## 概要

画面設計書の全てを knowledge の設計書のスキーマ `design-schemas/v12.0.0` で記載し直し、記載し直す途中で気づいた設計の漏れ・誤りを、実装とテストまで合わせて修正する。

## 背景

[Issue #353](https://github.com/shuhei1101/voice-paste/issues/353) の要望。
knowledge の `design-schemas/v12.0.0`（[shuhei1101/knowledge#602](https://github.com/shuhei1101/knowledge/issues/602)）で、画面設計に規約にあるのに記載する欄が無かった決まりの欄が追加された。
このリポジトリの配信元の設定 `project-index.yaml` は `design-schemas/v9.5.0` を参照しており、v12.0.0 へ上げると画面設計書 10 件（`docs/screen/SCR-1`〜`SCR-10`）が検査に通らない。
間のメジャー版 v10.0.0（入力を持たない値と固定の領域の値の `overflow` の必須）と v11.0.0（要素の `kind` の英語の enum と種類ごとの欄の必須・禁止）の変更も、同じ版上げで画面設計書に効く。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.mark.md) | 常駐アプリの計画書 |
