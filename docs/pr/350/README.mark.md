# 配信元の設定ファイル dev-docs.yaml を project-index.yaml へ改名する

## 概要

リポジトリの直下の配信元の設定ファイル `dev-docs.yaml` を `project-index.yaml` へ改名し、端末の設定の配信元の登録も改名後のファイルを指すようにする。

## 背景

[Issue #348](https://github.com/shuhei1101/voice-paste/issues/348) の要望。
project-index の配信元の設定の名前は `project-index.yaml` で、ai-monitor・knowledge・mdmark など他のプロジェクトは改名を終えているが、このリポジトリは旧名の `dev-docs.yaml` のまま残っている。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.mark.md) | 要望の整理 |
| [反映作業](./反映作業/index.yaml) | 端末の設定の書き換え |
