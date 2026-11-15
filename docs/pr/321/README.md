# publish で作り直した目次の README.md と _config.yml を commit して index.yaml と一致させる

## 概要

develop で `python -m ai_monitor.design_docs publish` を実行しても差分が出ないよう、publish で作り直した目次の README.md と `docs/_config.yml` を commit する。

## 背景

[Issue #306](https://github.com/shuhei1101/voice-paste/issues/306) の要望。
作業 PR [#300](https://github.com/shuhei1101/voice-paste/pull/300) で publish を実行すると、目次の README.md が作り直されて差分が出た。
publish の出力の表のマーカーが `<!-- table: data -->` で、[#297](https://github.com/shuhei1101/voice-paste/pull/297) で移した JSON の記載と合っていなかったため、[shuhei1101/ai-monitor#3418](https://github.com/shuhei1101/ai-monitor/issues/3418) の後に作り直す計画になった。
#3418 は close 済みで、AI Monitor の develop の publish は JSON の記載でマーカーを書く。

## 計画書

| ファイル | 中身 |
| --- | --- |
| `要件.md` | 要望の整理 |
