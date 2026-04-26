# PR8: 録音経過時間表示・文字起こし進捗バー・UI更新タイミング修正

## 概要

① 録音中モーダルに録音経過時間を表示する
② 文字起こしオーバーレイの残り時間を「残りX秒/総X秒」形式 + 進捗バーに変更
③ 文字起こし処理をバックグラウンドスレッドに移し、UIを0.1秒間隔で独立更新する

## 作業内容

- [ ] RecordingModal: 録音開始からの経過時間ラベルを追加
- [ ] TranscribingOverlay: 残り時間表示を「残りX秒/総X秒」形式に変更
- [ ] TranscribingOverlay: ttk.Progressbar で進捗バーを追加
- [ ] main.py: transcribe をバックグラウンドスレッドで実行し、
      メインスレッドが50msごとに overlay.tick() を呼ぶ構成に変更
- [ ] on_segment コールバックを (remaining, total) の2引数に変更

## 実装メモ

- RecordingModal: `_update_wave()` タイミングで経過時間ラベルを更新（mainloopで動くので問題なし）
- バックグラウンドスレッド: `transcribe()` → `on_segment(remaining, total)` で `self._remaining` / `self._total` をセット
- メインスレッド: `t.is_alive()` の間 `overlay.tick()` + `t.join(0.05)` でポーリング
- `overlay.update()` は tkinter 非呼び出し（値セットのみ）、`tick()` が tkinter を操作
- 進捗: `(total - remaining) / total * 100`
- ウィンドウ高さを進捗バー分調整

## テスト

- [ ] 録音中に経過時間が滑らかに更新されること
- [ ] 文字起こし中に UI が 0.1 秒間隔で滑らかに更新されること
- [ ] 「残りX秒/総X秒」と進捗バーが正しく表示されること
- [ ] transcribe 中に例外が発生してもエラーダイアログが出てアプリが継続すること
