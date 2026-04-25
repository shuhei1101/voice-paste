# PR4: 文字起こしエンジン選択機能（ローカル / OpenAI API）

## 概要

faster-whisper（ローカル推論）に加え、OpenAI Whisper API（クラウド）を
文字起こしエンジンとして選択できるようにする。
`.env` の手動編集または設定GUIから切り替え可能とし、再起動で反映する。

## 作業内容

- [ ] `openai` ライブラリを `pyproject.toml` に追加
- [ ] `voice_paste/transcription/openai_transcriber.py` 新規作成
      （`Transcribable` 実装、`whisper-1` モデル使用）
- [ ] `config.py` に `TRANSCRIPTION_ENGINE`・`OPENAI_API_KEY` 追加
- [ ] `main.py` でエンジン設定に応じて transcriber を切り替える分岐追加
- [ ] `settings_gui.py` にエンジン選択・APIキー入力欄を追加
- [ ] `.env.sample` にデフォルト値・コメント追加
- [ ] API呼び出し失敗時のエラー処理（アプリ継続、エラーメッセージ表示）

## 実装メモ

- エンジン設定: `TRANSCRIPTION_ENGINE=local`（デフォルト）/ `openai`
- APIキー: `OPENAI_API_KEY=sk-...`（`.env` または設定GUIから設定）
- `on_segment` コールバック: OpenAI は一括レスポンスのため、
  呼び出し完了後に一度だけ呼ぶ（波形アニメーションは待機中も継続）
- `initial_prompt`: OpenAI API も同パラメータ対応済み、用語集ヒントをそのまま渡す
- 失敗時: GUI にエラーメッセージを表示、アプリはトレイ常駐を維持（終了しない）

## テスト

- [ ] ローカルエンジンで従来通り動作すること
- [ ] OpenAIエンジンで音声が正しく文字起こしされること
- [ ] 無効なAPIキーでエラー表示され、アプリが終了しないこと
- [ ] 設定GUIからエンジン切り替え・APIキー変更→再起動で反映されること
