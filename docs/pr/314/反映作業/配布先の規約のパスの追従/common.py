"""配布先の rules.yaml・agent_context.yaml が指す AI Monitor の規約などの .md を、変換後の YAML のパスへ書き換える作業の共通部分。"""

import sys
from pathlib import Path

# 書き換える対象のファイル（配布先のリポジトリの直下から）
TARGETS = ("rules.yaml", "agent_context.yaml")
# 変換前のパス → 変換後のパス
MAPPING = {
    "docs/rule/MCPツール名.md": "docs/rule/rule-mcp-tool-name.yaml",
    "docs/rule/PR差分の取得.md": "docs/rule/rule-pr-diff.yaml",
    "docs/rule/ai-monitorの開発.md": "docs/rule/rule-ai-monitor-development.yaml",
    "docs/rule/インラインコメント.md": "docs/rule/rule-inline-comment.yaml",
    "docs/rule/コメント.md": "docs/rule/rule-comment.yaml",
    "docs/rule/サブエージェントの使用.md": "docs/rule/rule-subagent.yaml",
    "docs/rule/ターミナル出力.md": "docs/rule/rule-terminal-output.yaml",
    "docs/rule/テレメトリの参照.md": "docs/rule/rule-telemetry.yaml",
    "docs/rule/ドキュメントのオンデマンド取得.md": "docs/rule/rule-on-demand-docs.yaml",
    "docs/rule/ドキュメント管理.md": "docs/rule/rule-document-management.yaml",
    "docs/rule/フェーズ索引の網羅.md": "docs/rule/rule-phase-index-coverage.yaml",
    "docs/rule/ブランチ戦略.md": "docs/rule/rule-branch-strategy.yaml",
    "docs/rule/マージ手順.md": "docs/rule/rule-merge.yaml",
    "docs/rule/モック画面構成.md": "docs/rule/rule-mock-screen.yaml",
    "docs/rule/ユーザー確認が必須な事項.md": "docs/rule/rule-user-confirmation.yaml",
    "docs/rule/ルール改修の報告.md": "docs/rule/rule-rule-fix-report.yaml",
    "docs/rule/不具合の報告.md": "docs/rule/rule-defect-report.yaml",
    "docs/rule/会話からの起票.md": "docs/rule/rule-issue-from-conversation.yaml",
    "docs/rule/参照リンク.md": "docs/rule/rule-reference-link.yaml",
    "docs/rule/反映作業の実行.md": "docs/rule/rule-reflection-work.yaml",
    "docs/rule/変更の由来の調査.md": "docs/rule/rule-change-origin.yaml",
    "docs/rule/完了報告・指示の投稿.md": "docs/rule/rule-completion-report.yaml",
    "docs/rule/対象外の逸脱の報告.md": "docs/rule/rule-out-of-scope-deviation.yaml",
    "docs/rule/工程の定義.md": "docs/rule/rule-process-definition.yaml",
    "docs/rule/本文の部分的な書き戻し.md": "docs/rule/rule-partial-body-restore.yaml",
    "docs/rule/案のレビュー.md": "docs/rule/rule-proposal-review.yaml",
    "docs/rule/確認事項の投稿.md": "docs/rule/rule-confirmation-post.yaml",
    "docs/rule/自分宛コメントの取得とResolve.md": "docs/rule/rule-addressed-comments.yaml",
    "docs/rule/要件の記入.md": "docs/rule/rule-requirements-entry.yaml",
    "docs/rule/見積もりポイント.md": "docs/rule/rule-estimate-points.yaml",
    "docs/rule/議論中ラベル.md": "docs/rule/rule-discussion-label.yaml",
    "docs/rule/開発時の従量課金APIの実行.md": "docs/rule/rule-paid-api-execution.yaml",
    "docs/flowchart/Issueのラベル判定.md": "docs/flowchart/flowchart-issue-label.yaml",
    "docs/flowchart/タグの判定.md": "docs/flowchart/flowchart-plan-tag.yaml",
    "docs/flowchart/ドキュメント配置判定.md": "docs/flowchart/flowchart-document-placement.yaml",
    "docs/flowchart/モック要否.md": "docs/flowchart/flowchart-mock-necessity-am.yaml",
    "docs/flowchart/並列不可の判定.md": "docs/flowchart/flowchart-no-parallel.yaml",
    "docs/flowchart/反映方法の判定.md": "docs/flowchart/flowchart-reflection-method.yaml",
    "docs/flowchart/画面設計要否.md": "docs/flowchart/flowchart-screen-design-necessity-am.yaml",
    "docs/flowchart/計画の未着手の行との突き合わせ.md": "docs/flowchart/flowchart-plan-row-matching.yaml",
    "docs/checksheet/メジャーリリース前のテスト精査.md": "docs/checksheet/checksheet-major-release-test-review-am.yaml",
    "docs/checksheet/既存プロジェクトの取り込み.md": "docs/checksheet/checksheet-existing-project-intake.yaml",
    "docs/template/PRドキュメント-タスク一覧.md": "docs/template/template-pr-doc-tasks.yaml",
    "docs/template/PRドキュメント-反映作業.md": "docs/template/template-pr-doc-reflection-work.yaml",
    "docs/template/PRドキュメント-反映作業スクリプト.md": "docs/template/template-pr-doc-reflection-script.yaml",
    "docs/template/PRドキュメント-対象システム計画.md": "docs/template/template-pr-doc-system-plan.yaml",
    "docs/template/PRドキュメント-目次.md": "docs/template/template-pr-doc-index.yaml",
    "docs/template/PRドキュメント-確認ログ.md": "docs/template/template-pr-doc-confirmation-log.yaml",
    "docs/template/PRドキュメント-要件.md": "docs/template/template-pr-doc-requirements.yaml",
    "docs/template/やりたいことリスト.md": "docs/template/template-wishlist.yaml",
    "docs/template/フェーズ.md": "docs/template/template-phase.yaml",
    "docs/template/フェーズ索引.md": "docs/template/template-phase-index.yaml",
    "docs/template/プロジェクトのエージェント定義.md": "docs/template/template-project-agents.yaml",
    "docs/template/情報収集Issue.md": "docs/template/template-inbox-issue.yaml",
    "docs/template/連絡ボード.md": "docs/template/template-notice-board.yaml"
}


def repo_root(argv: list[str]) -> tuple[Path, bool]:
    """第 1 引数の配布先のリポジトリの直下と、--dry-run の有無を返す（不正なら前提確認で止める）。"""
    if len(argv) < 2 or len(argv) > 3 or (len(argv) == 3 and argv[2] != "--dry-run"):
        print("前提確認: failed")
        print(f"引数: {argv[1:]}")
        sys.exit(1)
    root = Path(argv[1])
    if not (root / ".git").exists():
        print("前提確認: failed")
        print(f"リポジトリでない: {root}")
        sys.exit(1)
    return root, len(argv) == 3


def rewrite(text: str) -> str:
    """変換前のパスを変換後のパスへ置き換えた本文を返す。"""
    for old, new in MAPPING.items():
        text = text.replace(old, new)
    return text
