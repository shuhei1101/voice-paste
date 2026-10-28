"""Linux の端末アプリへの貼り付けの手段を、VM の Xorg のセッションで確かめる PoC。"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pynput.keyboard import Controller, Key, KeyCode
from PySide6.QtWidgets import QApplication, QLabel
from Xlib import X, display

logger = logging.getLogger(__name__)

CLIPBOARD_TEXT = "ポック検証 clipboard\n2 行目"
PRIMARY_TEXT = "primary-sentinel"
NONE_TEXT = "none-sentinel"
# 録音の画面を閉じてから貼り付けのキーを送信するまでの待ち（本番の FOCUS_SETTLE_SEC と同じ値）
FOCUS_SETTLE_SEC = 0.1
# アプリの起動と、キー・ウィンドウの切り替えが落ち着くのを待つ時間
APP_START_SEC = 1.5
APP_START_TIMEOUT_SEC = 30.0
POLL_SEC = 0.5
ACTION_SETTLE_SEC = 0.5
COMMAND_TIMEOUT_SEC = 10.0
IDENTIFY_TRIALS = 10
TERM_OUT = Path("/tmp/poc_term.txt")
HTML_PATH = Path.home() / "poc_paste.html"
RESULT_PATH = Path.home() / "poc_result.json"
APPS = ("terminal", "editor", "firefox")

type KeyPart = Key | KeyCode | str


def xkey(char: str) -> KeyCode:
    """文字のキーを、XTEST で送る pynput のキーにする（Xorg の pynput では vk が keysym で、ASCII の文字は keysym と同じ値）。"""
    return KeyCode.from_vk(ord(char))


# 送り方ごとの、貼り付けのキーの組み合わせ
# sendevent: 本番の send_paste と同じく文字を渡す（pynput は XSendEvent で送る）
# xtest: 文字を vk で渡す（pynput は XTEST で送る）
PASTE_KEYS: dict[str, dict[str, tuple[KeyPart, ...]]] = {
    "sendevent": {
        "ctrl+v": (Key.ctrl, "v"),
        "ctrl+shift+v": (Key.ctrl, Key.shift, "v"),
        "shift+insert": (Key.shift, Key.insert),
    },
    "xtest": {
        "ctrl+v": (Key.ctrl, xkey("v")),
        "ctrl+shift+v": (Key.ctrl, Key.shift, xkey("v")),
        "shift+insert": (Key.shift, Key.insert),
    },
}
IDENTIFY_METHOD = "xtest"
IDENTIFY_KEY = "ctrl+v"


@dataclass(frozen=True, slots=True, kw_only=True)
class Identification:
    """アクティブなウィンドウを 1 回読んだ結果。"""

    app: str
    wm_class: list[str]
    elapsed_ms: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PasteResult:
    """1 つのアプリへ 1 つのキーを 1 つの送り方で送信した結果。"""

    app: str
    method: str
    key: str
    pasted: str
    matches_clipboard: bool
    is_primary: bool


def run(args: list[str]) -> str:
    """外部コマンドを実行して標準出力を返す。"""
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SEC).stdout


def list_windows(wm_class: str) -> list[str]:
    """WM_CLASS のインスタンス名に当たる、表示中のウィンドウの ID を返す。"""
    found = subprocess.run(
        ["xdotool", "search", "--onlyvisible", "--classname", wm_class],
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SEC,
        check=False,
    )
    # 当たるウィンドウが無いと xdotool は 1 で終わるので、空の一覧として扱う
    return found.stdout.split()


def launch_and_wait(args: list[str], wm_class: str) -> str:
    """アプリを起動し、新しく開いたウィンドウの ID を返す。"""
    before = set(list_windows(wm_class))
    subprocess.Popen(args)
    deadline = time.monotonic() + APP_START_TIMEOUT_SEC
    # 起動前に無かったウィンドウが現れるまで待つ
    while time.monotonic() < deadline:
        new = [w for w in list_windows(wm_class) if w not in before]
        if new:
            time.sleep(APP_START_SEC)
            return new[-1]
        time.sleep(POLL_SEC)
    raise TimeoutError(f"{wm_class} のウィンドウが {APP_START_TIMEOUT_SEC} 秒で開きませんでした")


def set_selection(selection: str, text: str) -> None:
    """xclip で CLIPBOARD か PRIMARY に文字を入れる。"""
    # xclip は選択の所有者として裏に残るので、書き込みだけ待って切り離す
    proc = subprocess.Popen(["xclip", "-selection", selection], stdin=subprocess.PIPE, text=True)
    proc.communicate(text)


def read_clipboard() -> str:
    """xclip で CLIPBOARD の文字を読む。"""
    return run(["xclip", "-o", "-selection", "clipboard"])


def activate(window_id: str) -> None:
    """xdotool でウィンドウを前面に出す。"""
    run(["xdotool", "windowactivate", "--sync", window_id])
    time.sleep(ACTION_SETTLE_SEC)


def flash_own_window(app: QApplication) -> None:
    """録音の画面に見立てた PySide6 の窓を前面に出してから閉じる。"""
    label = QLabel("録音の画面（PoC）")
    label.show()
    label.raise_()
    label.activateWindow()
    app.processEvents()
    time.sleep(ACTION_SETTLE_SEC)
    app.processEvents()
    label.close()
    app.processEvents()


def read_active_wm_class(xdisplay: display.Display) -> tuple[list[str], float]:
    """_NET_ACTIVE_WINDOW の WM_CLASS を読み、かかった時間（ms）とあわせて返す。"""
    started = time.perf_counter()
    root = xdisplay.screen().root
    atom = xdisplay.intern_atom("_NET_ACTIVE_WINDOW")
    prop = root.get_full_property(atom, X.AnyPropertyType)
    # アクティブなウィンドウが無いときは、空のクラス名として返す
    if prop is None or not prop.value:
        return [], (time.perf_counter() - started) * 1000
    window = xdisplay.create_resource_object("window", prop.value[0])
    wm_class = window.get_wm_class() or ()
    return list(wm_class), (time.perf_counter() - started) * 1000


def send_keys(keyboard: Controller, keys: tuple[KeyPart, ...]) -> None:
    """キーの組み合わせを押して離す。"""
    for key in keys:
        keyboard.press(key)
    for key in reversed(keys):
        keyboard.release(key)
    time.sleep(ACTION_SETTLE_SEC)


def prepare_and_identify(app: QApplication, xdisplay: display.Display, window_id: str, name: str) -> Identification:
    """選択を入れ、貼り付け先を前面に出し、窓を閉じた後の WM_CLASS を読む。"""
    set_selection("clipboard", CLIPBOARD_TEXT)
    set_selection("primary", PRIMARY_TEXT)
    activate(window_id)
    flash_own_window(app)
    time.sleep(FOCUS_SETTLE_SEC)
    wm_class, elapsed = read_active_wm_class(xdisplay)
    return Identification(app=name, wm_class=wm_class, elapsed_ms=elapsed)


def paste_terminal(
    app: QApplication, xdisplay: display.Display, keyboard: Controller, paste_keys: tuple[KeyPart, ...]
) -> tuple[Identification, str]:
    """GNOME Terminal の cat に貼り付け、入力を閉じた後のファイルを読む。"""
    TERM_OUT.unlink(missing_ok=True)
    window_id = launch_and_wait(["gnome-terminal", "--", "bash", "-c", f"cat > {TERM_OUT}"], "gnome-terminal-server")
    ident = prepare_and_identify(app, xdisplay, window_id, "terminal")
    send_keys(keyboard, paste_keys)
    # 1 回目で行の途中の文字を書き出し、2 回目で入力を閉じる
    send_keys(keyboard, (Key.ctrl, xkey("d")))
    send_keys(keyboard, (Key.ctrl, xkey("d")))
    pasted = TERM_OUT.read_text(encoding="utf-8") if TERM_OUT.exists() else ""
    # Ctrl+V は端末で次の文字をそのまま入れるキーになり、cat が残るので終わらせて端末を閉じる
    subprocess.run(["pkill", "-f", f"cat > {TERM_OUT}"], check=False, timeout=COMMAND_TIMEOUT_SEC)
    time.sleep(ACTION_SETTLE_SEC)
    return ident, pasted


def paste_text_widget(
    app: QApplication, xdisplay: display.Display, keyboard: Controller, paste_keys: tuple[KeyPart, ...], window_id: str, name: str
) -> tuple[Identification, str]:
    """Text Editor か Firefox の入力欄を空にして貼り付け、全選択してコピーした文字を読む。"""
    activate(window_id)
    # 前の回に貼り付けた文字を消す（全選択で PRIMARY が替わるので、選択を入れるより先に行う）
    send_keys(keyboard, (Key.ctrl, xkey("a")))
    send_keys(keyboard, (Key.delete,))
    ident = prepare_and_identify(app, xdisplay, window_id, name)
    send_keys(keyboard, paste_keys)
    # 貼り付けで何も入らなかったときに、前の CLIPBOARD を読み違えないよう替えておく
    set_selection("clipboard", NONE_TEXT)
    send_keys(keyboard, (Key.ctrl, xkey("a")))
    send_keys(keyboard, (Key.ctrl, xkey("c")))
    return ident, read_clipboard()


def run_trial(
    app: QApplication,
    xdisplay: display.Display,
    keyboard: Controller,
    name: str,
    paste_keys: tuple[KeyPart, ...],
    windows: dict[str, str],
) -> tuple[Identification, str]:
    """アプリ名に合う貼り付けの流れを 1 回実行する。"""
    # 端末は cat の出力をファイルから、ほかは入力欄をコピーして取り出す
    if name == "terminal":
        return paste_terminal(app, xdisplay, keyboard, paste_keys)
    return paste_text_widget(app, xdisplay, keyboard, paste_keys, windows[name], name)


def main() -> int:
    """送り方 2 つ × キー 3 つ × アプリ 3 つの貼り付けと、3 アプリ × 10 回の見分けを行い、結果を JSON に残す。"""
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    xdisplay = display.Display()
    keyboard = Controller()
    HTML_PATH.write_text('<!doctype html><meta charset="utf-8"><textarea autofocus autocomplete="off" rows="5"></textarea>', encoding="utf-8")
    windows = {
        "editor": launch_and_wait(["gnome-text-editor", "--new-window"], "gnome-text-editor"),
        "firefox": launch_and_wait(["firefox", "--new-window", HTML_PATH.as_uri()], "Navigator"),
    }

    identifications: list[Identification] = []
    pastes: list[PasteResult] = []
    # 1 巡目は送り方とキーの全ての組み合わせを試し、2 巡目からは見分けの回数を満たすまで同じ組み合わせで繰り返す
    for round_no in range(IDENTIFY_TRIALS):
        combos = [(m, k) for m in PASTE_KEYS for k in PASTE_KEYS[m]] if round_no == 0 else [(IDENTIFY_METHOD, IDENTIFY_KEY)]
        for method, key in combos:
            for name in APPS:
                ident, pasted = run_trial(app, xdisplay, keyboard, name, PASTE_KEYS[method][key], windows)
                logger.info("%s %s %s: wm_class=%s %.2fms pasted=%r", name, method, key, ident.wm_class, ident.elapsed_ms, pasted)
                # 見分けは同じ送り方・キーの回だけを数える
                if (method, key) == (IDENTIFY_METHOD, IDENTIFY_KEY):
                    identifications.append(ident)
                # 貼り付けの組み合わせは 1 巡目だけで判定する
                if round_no == 0:
                    pastes.append(
                        PasteResult(
                            app=name,
                            method=method,
                            key=key,
                            pasted=pasted,
                            matches_clipboard=pasted.rstrip("\n") == CLIPBOARD_TEXT,
                            is_primary=PRIMARY_TEXT in pasted,
                        )
                    )

    result = {"identifications": [asdict(i) for i in identifications], "pastes": [asdict(p) for p in pastes]}
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
