# dev/ を廃止して文書を docs/ 1 つにまとめ、AI Monitor の次のバージョンの配布物へ追従する

## 概要

`dev/` を廃止して voice-paste の文書を `docs/` 1 つにまとめ、AI Monitor の次のバージョン（[ai-monitor#3104](https://github.com/shuhei1101/ai-monitor/issues/3104)・[ai-monitor#2973](https://github.com/shuhei1101/ai-monitor/issues/2973)）の配布物へ追従する。

## 背景

[#270](https://github.com/shuhei1101/voice-paste/issues/270) の要望。
AI Monitor 自身の移行 [ai-monitor#3307](https://github.com/shuhei1101/ai-monitor/pull/3307) で、監視対象のプロジェクトも `docs/` だけで運用する前提に変わる。
この PR は ai-monitor#3307 のマージを待たずに進め、レビューに合格したらこのプロジェクトでマージする（[進め方の変更](https://github.com/shuhei1101/voice-paste/issues/270#issuecomment-6740438867)）。
[#257](https://github.com/shuhei1101/voice-paste/issues/257)（既存の文書の mdmark の記法への移行）がこの追従を前提にしている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と移し先の対応 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの設計書の移し先 |
| [文字起こしワーカー](./文字起こしワーカー.md) | 文字起こしワーカーの設計書の移し先 |
