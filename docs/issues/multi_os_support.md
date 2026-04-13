# マルチOS対応（Linux / Mac）

## 概要

現在Windows専用。Ubuntu（Linux GUI）やMacでも実行できるようにしたい。

## 前提

- PyInstallerはクロスコンパイル不可。Linux用はLinux上で、Mac用はMac上でビルドする必要がある
- コードの8割はそのまま動く。OS依存は残り2割

## コード変更が必要な箇所

### 1. gui.py — デュアルモニター検出
- 現状: `ctypes.windll.user32`（Win32 API）でカーソル位置のモニターを取得
- Linux: X11の`Xlib`やwayland用の対応が必要
- Mac: `AppKit`の`NSScreen`で取得可能
- 対応方針: `if sys.platform` で分岐、または `screeninfo` ライブラリで統一

### 2. keyboard_sender.py — 仮想キー入力
- 現状: `pynput` でCtrl+V / Enter送信
- Linux: X11環境ならpynputで動く。waylandだと非対応の場合あり
- Mac: pynputで基本動くが、アクセシビリティ権限が必要
- 対応方針: wayland対応が必要なら `xdotool` や `ydotool` にフォールバック

### 3. tray.py — システムトレイアイコン
- 現状: `pystray` を使用
- Linux: `AppIndicator3` が必要（`sudo apt install gir1.2-appindicator3-0.1`）
- Mac: pystrayで動く
- 対応方針: Linux向けにAppIndicatorの依存を追加

### 4. build_exe.bat — ビルドスクリプト
- 現状: Windows用batファイル
- 対応方針: `build.sh`（Linux/Mac用）を別途作成

### 5. CUDA / GPU対応
- Linux: CUDA対応可能（NVIDIAドライバ + CUDA Toolkit）
- Mac（Apple Silicon）: CUDAなし。`WHISPER_DEVICE=cpu` 固定
  - 高速化したい場合は CoreML 対応の whisper 実装（`mlx-whisper` 等）に差し替え検討
- Mac（Intel + NVIDIA）: 現在ほぼ存在しないので考慮不要

### 6. config.py — パス解決
- ほぼ変更不要（Pathlibを使っているので `/` と `\` の問題はない）
- `.env.sample` のコピー処理も `shutil` なのでOS問わず動く

## 優先度

1. **Linux（Ubuntu）対応**: GUI環境あり、CUDA使える、需要あり
2. **Mac対応**: CUDA使えない（CPU only）ので速度面で妥協が必要

## 参考

- pynput wayland対応状況: https://github.com/moses-palmer/pynput/issues
- pystray Linux対応: AppIndicator3 が必要
- screeninfo（クロスプラットフォームのモニター情報取得）: https://github.com/rr-/screeninfo
