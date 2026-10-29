"""最小の QSystemTrayIcon を出し、GNOME の上のバーに出るかを見る（PoC）。"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

app = QApplication(sys.argv)
pixmap = QPixmap(64, 64)
pixmap.fill(QColor("red"))
tray = QSystemTrayIcon(QIcon(pixmap))
menu = QMenu()
menu.addAction("終了", app.quit)
tray.setContextMenu(menu)
tray.setToolTip("poc tray")
tray.show()
print("available:", QSystemTrayIcon.isSystemTrayAvailable(), flush=True)
QTimer.singleShot(int(sys.argv[1]) * 1000 if len(sys.argv) > 1 else 15000, app.quit)
app.exec()
