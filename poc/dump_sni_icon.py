"""StatusNotifierItem の IconPixmap を PNG に書き出す（PoC）。"""

import subprocess
import sys

from PySide6.QtGui import QGuiApplication, QImage

bus_name, out = sys.argv[1], sys.argv[2]
raw = subprocess.run(
    ["busctl", "--user", "get-property", bus_name, "/StatusNotifierItem",
     "org.kde.StatusNotifierItem", "IconPixmap"],
    check=True, capture_output=True, text=True,
).stdout.split()
# a(iiay) {count} {w} {h} {len} bytes...
w, h, n = int(raw[2]), int(raw[3]), int(raw[4])
data = bytes(int(x) for x in raw[5 : 5 + n])
app = QGuiApplication(sys.argv)
# SNI の画素は ARGB32 のネットワークバイトオーダー
argb = bytearray()
for i in range(0, n, 4):
    a, r, g, b = data[i : i + 4]
    argb += bytes((b, g, r, a))
QImage(bytes(argb), w, h, QImage.Format.Format_ARGB32).save(out)
alpha = [data[i] for i in range(0, n, 4)]
lum = [sum(data[i + 1 : i + 4]) / 3 for i in range(0, n, 4) if data[i] > 128]
print({"opaque_pixels": sum(1 for a in alpha if a > 128), "mean_luminance_of_opaque": sum(lum) / len(lum) if lum else None})
