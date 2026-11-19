# dev-docs.yaml の documents[].schema を knowledge の design-schemas/v9.5.0 へ上げる

## 概要

`dev-docs.yaml` の `documents[].schema.ref` を knowledge の `design-schemas/v9.2.0` から `design-schemas/v9.5.0` へ上げ、`design_docs validate` と `design_docs publish` が終了の状態 0 で終わるようにする。

## 背景

[Issue #336](https://github.com/shuhei1101/voice-paste/issues/336) の要望。
[#335](https://github.com/shuhei1101/voice-paste/pull/335) で `documents[].schema.ref` を全ての行で `design-schemas/v9.2.0` に統一した。knowledge には、それより後の `design-schemas/v9.2.1`〜`design-schemas/v9.5.0` のタグがある。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.mark.md) | dev-docs.yaml のスキーマのバージョンを上げる計画書 |
