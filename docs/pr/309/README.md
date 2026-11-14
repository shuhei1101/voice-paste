# 設定の見本・既定値と src/voice_paste/ui/・tokens.toml の配置場所を決めて修正する

## 概要

設定の見本・既定値と、`src/voice_paste/ui/`・デザイントークン `tokens.toml` の配置場所を決めて移し、フォルダ構成を knowledge の規約の構成に合わせる。

## 背景

[Issue #308](https://github.com/shuhei1101/voice-paste/issues/308) の要望で、子 Issue [#301](https://github.com/shuhei1101/voice-paste/issues/301)・[#302](https://github.com/shuhei1101/voice-paste/issues/302) をまとめる。
どちらも作業 PR [#300](https://github.com/shuhei1101/voice-paste/pull/300) で作ったフォルダ構成の設計書 `docs/layout/LAY-1.yaml` を、knowledge の規約『フォルダ構成の切り方とレビュー』の観点で確認して見つかった。
設定の見本・既定値は直下・`resources/`・`config/` の 3 か所に散り、`ui/` は規約『トップレベルレイアウト + feature 内構造』のトップレベルの構成に無く、直下にコードとデザイントークンが混ざる。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの計画書 |
