# PR5: AI送信アプリの個別有効/無効設定

## 概要

AI送信アプリ（AI1・AI2）をそれぞれ個別に有効/無効で切り替えられるようにする。
無効にしたアプリのボタンは録音モーダルに表示しない。
設定は .env の手動編集または設定GUIから変更可能。

## 作業内容

- [ ] `config.py` に `AI_SEND_1_ENABLED` / `AI_SEND_2_ENABLED` を追加
- [ ] `.env.sample` にデフォルト値・コメント追加
- [ ] `settings_gui.py` に各AIの有効/無効コンボボックスを追加
- [ ] `gui.py` で無効なアプリのボタンを非表示にする

## 実装メモ

- 設定キー: `AI_SEND_1_ENABLED=true` / `AI_SEND_2_ENABLED=true`（デフォルト true）
- `config.py` の `AI_SEND_APPS` 読み込み時に `enabled` フラグを付与
- `gui.py` は `app.get("enabled", True)` が False のボタンをスキップ
- 設定GUIは各AIセクションに「有効」コンボボックス（true/false）を追加

## テスト

- [ ] AI1 を無効にするとボタンが消えること
- [ ] AI2 を無効にするとボタンが消えること
- [ ] 両方無効でAIボタン行ごと非表示になること
- [ ] 設定GUI変更→再起動で反映されること
