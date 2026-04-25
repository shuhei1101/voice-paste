# PR6: 貼り付けキーのカスタマイズ

## 概要

`send_paste()` がCtrl+Vハードコードになっているため、ターミナル等で
Ctrl+Shift+Vが必要な場合に対応できなかった。
`PASTE_KEY` 設定を追加し、貼り付けキーをカスタマイズできるようにする。

## 作業内容

- [ ] `config.py` に `PASTE_KEY` を追加（デフォルト: `ctrl+v`）
- [ ] `keyboard_sender.py` の `send_paste()` で `PASTE_KEY` を参照するよう変更
- [ ] `.env.sample` にデフォルト値・コメント追加
- [ ] `settings_gui.py` に貼り付けキー入力欄を追加

## 実装メモ

- 設定キー: `PASTE_KEY=ctrl+v`（デフォルト）/ `ctrl+shift+v` 等
- pynput の `Key` と `KeyCode` を組み合わせてカスタムキー送信を実装
- フォーマット: `ctrl+v` / `ctrl+shift+v`（`+` 区切りの小文字）
- 設定GUIはホットキー入力と同様のキャプチャUIを使用

## テスト

- [ ] デフォルト（ctrl+v）で従来通り動作すること
- [ ] ctrl+shift+v に変更してターミナルで貼り付けできること
- [ ] 設定GUI変更→再起動で反映されること
