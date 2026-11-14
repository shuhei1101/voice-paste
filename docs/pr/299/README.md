# モジュール構成『常駐アプリ / 録音セッション / service.py』の状態遷移図を mdmark の map で描く

## 概要

モジュール構成『常駐アプリ / 録音セッション / service.py』の `SessionManager` の状態遷移図を、mdmark の map で描く。

## 背景

[#284](https://github.com/shuhei1101/voice-paste/issues/284) の要望。
[#282](https://github.com/shuhei1101/voice-paste/pull/282) で設計書の Mermaid の図を map で囲んだが、map が `stateDiagram-v2` を描けなかったため、この図だけを Mermaid のまま残した。
map が `stateDiagram-v2` を描けるようになった（[shuhei1101/mdmark#531](https://github.com/shuhei1101/mdmark/pull/531)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
