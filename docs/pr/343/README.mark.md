# OpenAI API の文字起こしの LLM の呼び出しの設計書を作成し、実装を設計書に合わせる

## 概要

OpenAI API の文字起こしを LLM の呼び出しとして、knowledge のテンプレート `template-llm-call` に沿った設計書を作成し、実装を設計書に合わせる。

## 背景

[#342](https://github.com/shuhei1101/voice-paste/issues/342) の要望。
[shuhei1101/ai-monitor#3743](https://github.com/shuhei1101/ai-monitor/issues/3743) で AI Monitor の設計の工程に「エージェントフロー・LLM 呼び出し設計」が入ったが、このリポジトリの LLM の呼び出し（`gpt-transcribe` 系のモデルへ手がかりの語を渡す OpenAI API の文字起こし）には、テンプレートに沿った設計書が無い。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.mark.md) | 常駐アプリの計画書 |
