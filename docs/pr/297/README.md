# 文書のマーカーを mdmark の JSON の記載へ移す

## 概要

このリポジトリの Markdown の文書のマーカーを、今の書き方（`<!-- table: data -->`）から mdmark v0.11.0 の JSON の記載へ移す。

## 背景

[Issue #294](https://github.com/shuhei1101/voice-paste/issues/294) の要望。
[shuhei1101/mdmark#477](https://github.com/shuhei1101/mdmark/pull/477) で、マーカーの設定を名前の後ろの JSON のオブジェクトで記載できるようになり、今の書き方を書き換える移行の手順（`mdmark upgrade`）が v0.11.0 から入った（[shuhei1101/mdmark#528](https://github.com/shuhei1101/mdmark/issues/528) でタグを打った）。
今の書き方は 1 つのマイナーバージョンの間だけ参照され、[shuhei1101/mdmark#479](https://github.com/shuhei1101/mdmark/issues/479) で参照する処理が削除される。
依頼元は [shuhei1101/mdmark#520](https://github.com/shuhei1101/mdmark/pull/520)（起点 Issue [shuhei1101/mdmark#478](https://github.com/shuhei1101/mdmark/issues/478)）。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
