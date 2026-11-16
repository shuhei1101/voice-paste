# AI Monitor v0.5.0 の配布物へ追従する

## 概要

voice-paste が追従している AI Monitor の配布物を v0.4.0 から v0.5.0 へ上げる。

## 背景

[Issue #325](https://github.com/shuhei1101/voice-paste/issues/325) の要望。
AI Monitor の v0.5.0 で、ドキュメントサイトが mdmark を `docs/_theme/assets/vendor/mdmark/` の同梱ではなく jsDelivr から読むようになり、`design_docs generate` が生成する図が mdmark の `map` のノードの種類を使うようになった（[ai-monitor#3462](https://github.com/shuhei1101/ai-monitor/pull/3462)）。
voice-paste の `ai-monitor-version.ini` と `ai-monitor-theme.yaml` は v0.4.0 のままで、リポジトリの直下に `mdmark.config.yaml` が無い。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [反映作業](./反映作業/index.yaml) | 配布元からコピーした反映作業の一覧 |
