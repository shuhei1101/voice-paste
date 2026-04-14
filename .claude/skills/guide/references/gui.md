# GUI関連

## ファイル一覧

| ファイル | 概要 |
|---------|------|
| `voice_paste/gui.py` | 録音モーダル — 録音中の波形表示、確定/キャンセルボタン |
| `voice_paste/settings_gui.py` | 設定ウィンドウ — Whisper設定・ホットキー・ログレベルの変更UI |
| `voice_paste/tray.py` | システムトレイ — アイコン・メニュー（録音開始/ログ/設定/終了） |

## GUI技術スタック

- **GUIフレームワーク**: tkinter（標準ライブラリ）
- **トレイ**: pystray + Pillow
- **テーマ**: ダークテーマ（背景 `#1e1e1e`、アクセント `#0078d4`）
- **ホットキーキャプチャ**: pynputリスナーによるリアルタイム取得

## よくある改修

- **録音モーダルのUI変更**: `voice_paste/gui.py` を編集
- **設定ウィンドウに項目追加**: `voice_paste/settings_gui.py` の `show()` メソッドにウィジェット追加
- **トレイメニュー変更**: `voice_paste/tray.py` を編集
- **テーマ・色変更**: 各GUIファイルの色定数（`_BG`, `_FG`, `_ACCENT` 等）
