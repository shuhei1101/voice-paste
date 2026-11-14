# AI Monitor v0.4.0 の配布物へ追従する

## 概要

voice-paste が追従している AI Monitor の配布物を v0.3.0 から v0.4.0 へ上げる。

## 背景

[Issue #313](https://github.com/shuhei1101/voice-paste/issues/313) の要望。
AI Monitor の v0.4.0 で、設計書のスキーマが各プロジェクトのコピーから knowledge の参照へ変わり、ルール索引の置き場所が `docs/rules.yaml` から直下の `rules.yaml` へ変わった。
voice-paste の `ai-monitor-version.ini` は v0.3.0 のままで、`schemas/` に AI Monitor から配られたスキーマのコピーが残っている。

[#307](https://github.com/shuhei1101/voice-paste/issues/307) を #313 へ統合した。
[#285](https://github.com/shuhei1101/voice-paste/issues/285)・[#298](https://github.com/shuhei1101/voice-paste/issues/298) はこの追従を前提にしている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
| [常駐アプリ](./常駐アプリ.md) | 常駐アプリの ER 図とデータの設計書の計画書 |
| [反映作業](./反映作業/index.yaml) | 配布元からコピーした反映作業の一覧 |
