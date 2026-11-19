# dev-docs.yaml の documents[].schema を design-schemas/v9.2.0 へ統一し、design_docs publish が終了の状態 0 で終わるようにする

## 概要

`dev-docs.yaml` の `documents[].schema` が指す knowledge のリビジョンを 1 つに統一し、`python -m ai_monitor.design_docs publish` が終了の状態 0 で終わるようにする。

## 背景

[Issue #334](https://github.com/shuhei1101/voice-paste/issues/334) の要望。
[shuhei1101/ai-monitor#3691](https://github.com/shuhei1101/ai-monitor/issues/3691) で develop（00b9eac）へ `publish` を実行したときに見つかった。
`documents[].schema` の ref が knowledge の `design-schemas/v8.3.0`（19 行）と `design-schemas/v9.2.0`（files_repo・files_docs・files_guide の 3 行。[#329](https://github.com/shuhei1101/voice-paste/pull/329)・[#333](https://github.com/shuhei1101/voice-paste/pull/333) で入った）に分かれており、`publish` が行ごとに「リビジョンが揃っていません」を出して止まる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.mark.md) | 常駐アプリの設計書の refs の移行の計画書 |
| [Haas の文字起こしのサーバー](./Haasの文字起こしのサーバー.mark.md) | Haas の文字起こしのサーバーの設計書の refs の移行の計画書 |
