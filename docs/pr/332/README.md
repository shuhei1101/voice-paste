# テスト実行方法の run_runner で run を参照できるまで待ってから gh run watch を呼ぶ

## 概要

テスト実行方法の `run_runner` で、起動した run を API で参照できるまで待ってから `gh run watch` を呼び、ランナーの結果を受け取れるようにする。

## 背景

[Issue #331](https://github.com/shuhei1101/voice-paste/issues/331) の要望。
テスト実行方法の `run_runner` は、`gh workflow run` の直後に `gh run watch "$run_id"` を呼ぶ。
run がまだ API で参照できない間は `failed to get run: HTTP 404` で終わり、ランナーの集計の行を受け取れない。

同じ修正は [project-index#139](https://github.com/shuhei1101/project-index/pull/139) と claude-balancer の TP-275-1 に入っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [CI](./CI.md) | テスト実行方法の `run_runner` の計画書 |
