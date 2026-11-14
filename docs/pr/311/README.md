# haas_server/ のマニフェスト・起動スクリプト・コードを分けて配置する

## 概要

`haas_server/` の直下に平らに並ぶマニフェスト・起動スクリプト・コードを分けて配置し、起動の手順・テスト・設計書を移した後の構成に合わせる。

## 背景

[Issue #303](https://github.com/shuhei1101/voice-paste/issues/303) の要望。
作業 PR [#300](https://github.com/shuhei1101/voice-paste/pull/300) で作ったフォルダ構成の設計書 [docs/layout/LAY-1.yaml](https://github.com/shuhei1101/voice-paste/blob/7d9ae053c7ce87a869492c465d3ada707cca6a6b/docs/layout/LAY-1.yaml) を、knowledge の規約『フォルダ構成の切り方とレビュー』のレビューの観点「種類が混ざる」で確認して見つかった。
`haas_server/` は常駐アプリとは別の Python のプロジェクトで、`pyproject.toml`・`uv.lock`・`start.sh`・`main.py`・`app.py`・`audio.py`・`__init__.py` を直下に持ち、src レイアウトになっていない。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [Haasの文字起こしのサーバー](./Haasの文字起こしのサーバー.md) | Haas の文字起こしのサーバーの計画書 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
