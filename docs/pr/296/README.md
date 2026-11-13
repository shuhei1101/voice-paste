# API の参照資料に、別の端末のブラウザから録音を操作するときは呼び出し元の画面が Wake Lock を取ることを記載する

## 概要

API を呼ぶほかのシステムの開発者が、別の端末のブラウザから録音を操作するときに、その端末の画面が暗くならないよう呼び出し元の画面で Screen Wake Lock を取る必要があると、API の参照資料から分かるようになる。

## 背景

[Issue #295](https://github.com/shuhei1101/voice-paste/issues/295) の要望。
[#292](https://github.com/shuhei1101/voice-paste/pull/292)（起点 [#290](https://github.com/shuhei1101/voice-paste/issues/290)）で、常駐アプリが録音中に PC の画面の消灯を抑止し、外の端末の画面（`/web/`）が Screen Wake Lock を取るようにした。
API を呼ぶほかのシステム（MindStella の音声入力など）の画面を別の端末のブラウザで開いて録音を操作する場合、常駐アプリの抑止はその端末の画面に効かない。
呼び出し元の画面の変更は [shuhei1101/mindstella#513](https://github.com/shuhei1101/mindstella/issues/513) で扱う。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
