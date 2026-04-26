# PR9: プロンプト機能（initial_prompt）の削除

## 概要

Whisper が initial_prompt をそのまま出力に echo してしまうバグが頻発するため、
プロンプト機能を全削除する。
yogo.csv による後処理の単純文字列置換は信頼できるため残す。

## 削除対象

- [ ] `resources/prompt.txt` を削除
- [ ] `config.py` から `PROMPT_FILE` を削除
- [ ] `.env.sample` から `PROMPT_FILE` を削除
- [ ] `settings_gui.py` からプロンプトファイル UI を削除
- [ ] `utils.py` から `load_prompt()` / `build_initial_prompt()` を削除
- [ ] `main.py` からプロンプト読み込み・受け渡しを削除
- [ ] `whisper_transcriber.py` から `prompt` 引数と `initial_prompt` 渡しを削除
- [ ] `openai_transcriber.py` から `prompt` 引数と `prompt` 渡しを削除
- [ ] `transcribable.py` から `prompt` 引数を削除

## 残すもの

- `yogo.csv` / `utils.load_yogo()` / `utils.apply_yogo_replacements()` （後処理置換）
- 設定GUIの「用語集ファイル」項目

## テスト

- [ ] 短い音声でプロンプトの echo 出力が出ないこと
- [ ] yogo 置換が引き続き動作すること
- [ ] 設定GUIにプロンプトファイル項目が表示されないこと
