# PR2: AI送信ボタン機能の追加

## 概要

録音確定後のモーダルに「AI送信」ボタンを追加する。ボタン押下で指定したAIアプリ（Edge PWAとして登録済みのChatGPT・Google AI等）を新規ウィンドウで起動し、文字起こしテキストを自動貼り付け＋Enterで送信する。

## 作業内容

- [ ] `config.py` に AI送信設定を追加（`AI_SEND_N_NAME` / `AI_SEND_N_URL` / `AI_SEND_DELAY` / `AI_SEND_HOTKEY`）
- [ ] `.env.sample` に設定例を追加（ChatGPT / Google AI）
- [ ] `gui.py` に AI送信ボタンを動的生成（設定したアプリ数だけ自動追加）
- [ ] `gui.py` にホットキー `<ctrl>+<alt>+a`（1番目のAIアプリ）を追加
- [ ] `input/keyboard_sender.py` にAI送信ロジック実装（Edge起動 → 待機 → Ctrl+V → Enter）
- [ ] `main.py` に `send_to_ai` モード対応を追加
- [ ] `settings_gui.py` にAI送信設定UIを追加（任意）

## 実装詳細

### 設定（.env）

```
# AI送信アプリ設定（複数設定可、番号は1始まり）
AI_SEND_1_NAME=ChatGPT
AI_SEND_1_URL=https://chatgpt.com
AI_SEND_2_NAME=Google AI
AI_SEND_2_URL=https://gemini.google.com/app
AI_SEND_DELAY=2.5        # 起動後の待機秒数
AI_SEND_HOTKEY=<ctrl>+<alt>+a   # 1番目のアプリ用ホットキー
```

### ConfirmMode 拡張

`send_to_ai_0`, `send_to_ai_1` ... のようにアプリインデックスを含む形式で拡張。

### AI送信フロー

1. テキストをクリップボードにコピー
2. `msedge --app={URL} --new-window` でEdge PWAを起動
3. `AI_SEND_DELAY` 秒待機
4. pynput で Ctrl+V → Enter を送信

### Edge パス解決

`where msedge` → レジストリ → デフォルトパスの順で自動検索。

## テスト観点

- ChatGPT / Google AI それぞれでテキストが正しく貼り付け・送信されること
- 設定が0件の場合はボタンが表示されないこと
- ホットキーが競合しないこと
