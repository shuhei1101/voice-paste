# PR2: AI送信ボタン機能の追加

## 概要

録音確定後のモーダルに「AI送信」ボタンを追加する。ボタン押下で指定したAIアプリ（Edge PWAとして登録済みのChatGPT・Google AI等）を新規ウィンドウで起動し、文字起こしテキストを自動貼り付け＋Enterで送信する。

## 作業内容

- [x] `config.py` に AI送信設定を追加（`AI_SEND_N_NAME` / `AI_SEND_N_URL` / `AI_SEND_N_HOTKEY` / `AI_SEND_DELAY`）
- [x] `.env.sample` に設定例を追加（ChatGPT / Google AI、Ctrl+Alt+1/2 デフォルト）
- [x] `gui.py` に AI送信ボタンを動的生成（設定したアプリ数だけ自動追加）
- [x] `gui.py` にアプリ毎のホットキー登録（`AI_SEND_N_HOTKEY`）
- [x] `gui.py` ウィンドウ高さを AI ボタン有無に応じて動的調整
- [x] `input/keyboard_sender.py` にAI送信ロジック実装（Edge起動 → 待機 → Ctrl+V → Enter）
- [x] `main.py` に `send_to_ai` モード対応を追加
- [x] `settings_gui.py` にAI送信設定UIを追加（Name/URL/Hotkey × 2 + Delay）

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
