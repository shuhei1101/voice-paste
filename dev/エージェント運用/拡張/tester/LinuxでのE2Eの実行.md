# Linux での E2E の実行

release PR の対象ケースを、Windows での全 pass の後に検証環境の VM `voice-paste-ubuntu`（Ubuntu 24.04 の Xorg のセッション）でも流し、結果を報告する

## 手順

### VM への疎通の確認

`ssh -o BatchMode=yes voice-paste-ubuntu true` を流す。

- 終了コードが 0 でなく、release PR に未解決の `## VM の起動の依頼` のスレッドが無い場合、MCP `create_file_comment` で release PR へ `receiver` をユーザーにして投稿する。`body` は `## VM の起動の依頼` の見出しから始め、VM `voice-paste-ubuntu` を起動して Xorg のセッションへログインし、このスレッドへ返信してほしい旨を書く。続けて `議論中` を付け、MCP `set_assignee` で待ち、「作業完了報告」へ進む（以降の手順は実行しない）
- 終了コードが 0 でなく、未解決の `## VM の起動の依頼` のスレッドにユーザーの返信がある場合、まだ SSH が通らない旨をそのスレッドへ返信し、`議論中` を付け、MCP `set_assignee` で待ち、「作業完了報告」へ進む（以降の手順は実行しない）
- 終了コードが 0 の場合、未解決の `## VM の起動の依頼` のスレッドがあれば MCP `resolve_review_threads` で Resolve する

### 対象ケースの実行

開発コマンドの `テスト` の分類（検証環境の VM で流す手順）の手順 1〜4 で、release ブランチを VM の作業用のクローンへ送り、対象ケースを流してログを取ってくる。
対象ケースは、release PR の最後の Windows の実行の結果の報告に並んだケースで、手順 3 の `tests/e2e` の代わりに pytest のノード ID で並べて渡す。

### fail したケースの再実行

ログに fail したケースがある場合、そのケースだけを開発コマンドの手順 3〜4 でノード ID を並べて VM で流し直す。
流し直して pass したケースは `pass` として扱う。

### 結果の報告

MCP `create_file_comment` を呼ぶ:
- `pr_number`: release PR の番号
- `sender`: `tester`
- `receiver`: `tester`
- `body`: 先頭に `## Linux での E2E の結果` の見出しを置き、流した release の位置（commit）と、対象ケースをケースごとに `pass` / `fail` / `skip` のいずれかを添えた 1 行で並べる。テスト実行方法『E2E テスト』の前提にある Linux で skip するケース（Ctrl+Break・外の端末の画面）は一覧に並べず、本文の末尾の `### Linux で skip するケース` の項に `-rs` の skip の理由とともに書く。流し直したケースがあれば、本文の末尾の `### VM で流し直したケース` の項に書く。fail か skip のケースがある場合、流し直しは VM で済ませており、Windows で流し直して `## 起票しない判定` にしない旨を書く

### 作業完了報告

MCP `report_completion` を呼ぶ:
- `agent_name`: `tester`
- `number`: $number
- `next_turn`: release PR の番号（「VM への疎通の確認」で待機に入った場合は `no_handoff`）
