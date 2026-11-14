# .gitignore に .claude/worktrees/ を加える

## 概要

作業ブランチの worktree の置き場所 `.claude/worktrees/` を、どのクローンでも Git の管理から外す。

## 背景

[Issue #305](https://github.com/shuhei1101/voice-paste/issues/305) の要望。
`.gitignore` に `.claude/worktrees/` が無く、手元のクローンの `.git/info/exclude` の `**/.claude/worktrees/` だけで除外しているため、別のクローンでは除外されない。
フォルダ構成の設計書 `docs/layout/LAY-1.yaml` を作った作業 PR [#300](https://github.com/shuhei1101/voice-paste/pull/300)（起点 [Issue #269](https://github.com/shuhei1101/voice-paste/issues/269)）で、knowledge の規約『フォルダ構成の切り方とレビュー』のレビューの観点「管理しないもの」で確認して見つかった。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |
