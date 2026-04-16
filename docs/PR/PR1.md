## 概要
Ubuntu（Linux X11）対応

## 作業内容
- [ ] OS判定モジュール `voice_paste/platform.py` を追加（`PLATFORM` を `sys.platform` + 環境変数 `VOICE_PASTE_OS` から決定）
- [ ] `__main__.py` の CUDA DLL 登録を Windows 限定にガード
- [ ] `gui.py` のカーソル位置モニター検出を `screeninfo` ベースに統一
- [ ] `input/keyboard_sender.py` を `KeyboardSender` 抽象 + `WindowsKeyboardSender` / `LinuxKeyboardSender` にクラス分割
- [ ] `tray.py` の `os.startfile` / `xdg-open` 分岐を OS判定モジュール経由に整理
- [ ] `pyproject.toml` に `screeninfo` を追加
- [ ] `setup/setup_venv.sh` と `setup/build_linux.sh` を追加（Linux向け。exeではなく単一ELFバイナリ）
- [ ] `run.sh` / `run_resident.sh` を追加
- [ ] `config.py` にOS別デフォルト値（ホットキー・Whisperデバイス）を導入
- [ ] README またはドキュメントに Ubuntu セットアップ手順を追記（AppIndicator3 の apt 依存含む）
- [ ] Ubuntu 実機 / VirtualBox で動作確認（録音→文字起こし→貼り付け）
- [ ] `docs/issues/multi_os_support.md` を更新（Ubuntu対応完了を反映、Mac/Wayland は未対応として残す）

## 実装
| 追加/編集 | ファイルパス                         | クラス.メソッド                        | 変更内容                                                                                                                       |
| --------- | ------------------------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 追加      | voice_paste/platform.py              | PLATFORM                               | `"windows"`/`"linux"` を返す定数（env `VOICE_PASTE_OS` で上書き可）                                                            |
|           |                                      | is_windows / is_linux                  | 便利関数                                                                                                                       |
| 編集      | voice_paste/__main__.py              | _register_bundled_cuda_dlls            | Windows 以外では早期 return                                                                                                    |
| 編集      | voice_paste/gui.py                   | _get_cursor_monitor_rect               | `screeninfo` でカーソル位置のモニター矩形を取得（Win32 API削除）                                                               |
| 編集      | voice_paste/input/keyboard_sender.py | KeyboardSender (ABC)                   | `copy_to_clipboard` / `send_paste` / `send_enter` を定義                                                                       |
|           |                                      | WindowsKeyboardSender                  | pynput + pyperclip 実装（現行踏襲）                                                                                            |
|           |                                      | LinuxKeyboardSender                    | pynput + pyperclip 実装（X11前提）                                                                                             |
|           |                                      | get_sender                             | PLATFORM に応じたインスタンスを返すファクトリ                                                                                  |
| 編集      | voice_paste/tray.py                  | _open_log_folder / _open_config_folder | `sys.platform.startswith("win")` を `platform.is_windows()` に差し替え                                                         |
| 編集      | pyproject.toml                       | -                                      | `screeninfo` を dependencies に追加。`nvidia-*` を `platform_system == "Windows" or platform_system == "Linux"` 条件に（任意） |
| 編集      | voice_paste/config.py                | -                                      | OS別デフォルト（Linux: `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8`, `WHISPER_MODEL=large-v3`、ホットキー修飾子の違いを吸収） |
| 追加      | setup/setup_venv.sh                  | -                                      | venv作成 + pip install -e .（AppIndicator3 apt install の案内コメント含む）                                                    |
| 追加      | setup/build_linux.sh                 | -                                      | PyInstaller ビルド（Linux用。単一ELFバイナリを出力）                                                                           |
| 追加      | run.sh                               | -                                      | `python -m voice_paste` 起動（ワンショット）                                                                                   |
| 追加      | run_resident.sh                      | -                                      | 常駐モード起動                                                                                                                 |

## テスト
| 追加/編集 | ファイルパス           | テスト対象ファイルパス  | クラス.メソッド                               | 変更内容                            |
| --------- | ---------------------- | ----------------------- | --------------------------------------------- | ----------------------------------- |
| 追加      | tests/test_platform.py | voice_paste/platform.py | TestPlatform.test_default / test_env_override | `VOICE_PASTE_OS` の上書き動作を検証 |

手動確認（Ubuntu実機/VirtualBox）:
- [ ] ホットキーで録音開始
- [ ] 波形モーダルがカーソル位置のモニターに表示される
- [ ] 確定で文字起こし → Ctrl+V で貼り付け成功
- [ ] トレイアイコン表示・メニュー動作
- [ ] 設定ウィンドウ表示

## 設計メモ

- **OS切り替えの一元化**: `voice_paste.platform` モジュールで `PLATFORM` を決定し、他モジュールはこれを参照。環境変数 `VOICE_PASTE_OS=linux` で強制上書き可能（WSLなどの検証用途）。
- **Windowsの処理は残す**: すべてのOS分岐は「Windowsを消す」のではなく「Linux分岐を追加」する方針。Windowsは今後も主要動作環境。
- **クラス分割の基準**: 差分が大きい `keyboard_sender` のみクラス分割。`tray.py` / `gui.py` / `__main__.py` は if文で対応（小さい差分）。
- **OS別デフォルト**:
  - Windows: 従来どおり（`WHISPER_DEVICE=cuda`, モデルは既存.env準拠）
  - Linux: `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8`, `WHISPER_MODEL=large-v3`（CUDA環境の有無が不明なので安全側のCPU。品質は最高モデルでカバー）
  - ホットキー: 修飾キー自体（Ctrl/Alt）はWindows/Linux共通で存在するが、デスクトップ環境との衝突を避けるためOS別デフォルトを持てるようにする（`Super`はLinuxではWinキー相当）
- **ビルド成果物の命名**: Linuxは .exe ではなく拡張子なしの単一ELFバイナリ。スクリプト名も `build_linux.sh`。
- **常駐モードの命名**: Linuxでも通知領域（AppIndicator経由のインジケータ）は存在するが「タスクトレイ」という呼称はWindows寄りなので、起動スクリプト名は `run_resident.sh`（常駐モード）とする。
- **Wayland**: 今回対象外。X11（Xorg）のみ。ユーザー環境（Amazon WorkSpaces Ubuntu）はX11で確認済み。
- **Mac**: 今回対象外。
- **pystray on Linux**: AppIndicator3 ランタイム依存（`sudo apt install gir1.2-ayatanaappindicator3-0.1` 相当）が必要。Python依存には含まれないためドキュメントで案内。

## リスク
- faster-whisper の CUDA on Linux は libcudnn / libcublas の配置要件が Windows と異なる。実機で CPU fallback から検証する方針。
- `screeninfo` 置き換えで Windows のマルチモニター挙動が変わる可能性 → 置き換え後に Windows 側も回帰確認必要。
