# 配信元 voice-input の検索の対象とメタデータを project-index の setup の推奨に合わせて見直す

## 概要

配信元 voice-input の検索の対象を project-index の setup の推奨の範囲に合わせ、メタデータを今の付け方で見直す。

## 背景

[Issue #330](https://github.com/shuhei1101/voice-paste/issues/330) の要望。
project-index の setup が推奨する検索の範囲（`**/*`）と、メタデータの付け方（ファイルの中身を段階的に参照して付ける）が project-index の develop に入った（[shuhei1101/project-index#101](https://github.com/shuhei1101/project-index/issues/101)・[shuhei1101/project-index#102](https://github.com/shuhei1101/project-index/issues/102)）。
この配信元の `dev-docs.yaml` の `documents[]` と管理用の YAML（`files.yml`）は、それより前の範囲と付け方のままで、`tests/`・`docs/mock/` のコードと各フォルダの `README.md` が検索の対象に入っていない。
直下と `docs/` 直下のファイルを管理用の YAML に記載できるようにする [shuhei1101/project-index#133](https://github.com/shuhei1101/project-index/issues/133) は close 済み。

## 計画書

| ファイル | 中身 |
| --- | --- |
| [要件](./要件.md) | 要望の整理 |

## テスト結果

単体・結合テストは実行しない。変更は配信元の設定（`dev-docs.yaml`）と管理用の YAML（`files.yml`）だけで、規約『V字モデル』の対応表で対応するテストが無い。

代わりに、作業ブランチの `dev-docs.yaml` を project-index の develop（`7a95944`）の `check_project` で検査し、違反なし・索引の同期のずれなし（管理用の YAML に無いファイル・ファイルが無い行・`metadata` の列が無い文書がどれも 0 件）を確かめた。
