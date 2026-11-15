# 配信する .js の Content-Type を端末に依らず決まるようにし、ランナーの単体テストを pass させる

## 概要

外の端末の画面が読む `.js` の素材を、どの端末で動かしても同じ Content-Type で返却し、`test_mount_web_assets` をランナーと手元の両方で pass させる。

## 背景

[Issue #322](https://github.com/shuhei1101/voice-paste/issues/322) の要望。
作業 PR [#320](https://github.com/shuhei1101/voice-paste/pull/320) でテストの全件実行の workflow をランナー（`windows-latest`）で回したところ、`test_mount_web_assets` だけが fail した（[実行](https://github.com/shuhei1101/voice-paste/actions/runs/43703560120)）。
`mount_web_assets` は `StaticFiles` をそのまま組み込み、Content-Type を Python の `mimetypes` で決める。
Windows の `mimetypes` はレジストリの `.js` の Content Type を読むため、ランナーでは `application/javascript`、手元では `text/javascript` になる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理と変更箇所の由来 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
