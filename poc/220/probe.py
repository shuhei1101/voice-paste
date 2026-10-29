"""PoC: テキスト欄の中身を変わるたびにファイルへ書き出し、受けたキーを別のファイルへ追記するプローブアプリ。"""
import sys, time
from pathlib import Path
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QPlainTextEdit

out = Path(sys.argv[1])
keylog = out.with_suffix(".keys")
app = QApplication(sys.argv)
edit = QPlainTextEdit()
edit.setWindowTitle(f"probe-{app.platformName()}")
edit.resize(600, 300)


class KeyLogger(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            with keylog.open("a", encoding="utf-8") as f:
                f.write(f"{time.time():.3f} {event.key():#x} mods={event.modifiers().value:#x}\n")
        elif event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            with keylog.open("a", encoding="utf-8") as f:
                f.write(f"{time.time():.3f} {event.type().name}\n")
        return False


logger = KeyLogger()
edit.installEventFilter(logger)
edit.textChanged.connect(lambda: out.write_text(edit.toPlainText(), encoding="utf-8"))
out.write_text("", encoding="utf-8")
keylog.write_text("", encoding="utf-8")
edit.show()
edit.activateWindow()
sys.exit(app.exec())
