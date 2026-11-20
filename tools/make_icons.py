"""Render assets/logo.svg to PNG sizes and a multi-size Windows .ico (run once after editing the logo)."""
import os
import sys

from PIL import Image
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


def render(svg: bytes, size: int) -> QImage:
    r = QSvgRenderer(QByteArray(svg))
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841
    svg = open(os.path.join(ASSETS, "logo.svg"), "rb").read()
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        render(svg, s).save(os.path.join(ASSETS, f"logo_{s}.png"))
    big = Image.open(os.path.join(ASSETS, "logo_256.png"))
    big.save(os.path.join(ASSETS, "logo.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # installer wizard images (Inno Setup): large 164x314 side panel and 55x55 small
    side = Image.new("RGB", (164, 314), (40, 36, 92))
    for y in range(314):
        t = y / 313
        c = (int(76 + (155 - 76) * t), int(125 + (77 - 125) * t), int(255 + (234 - 255) * t))
        for x in range(164):
            side.putpixel((x, y), c)
    logo = Image.open(os.path.join(ASSETS, "logo_128.png")).convert("RGBA")
    side.paste(logo, (18, 90), logo)
    side.save(os.path.join(ASSETS, "wizard_large.bmp"))
    small = Image.new("RGB", (55, 55), (255, 255, 255))
    sl = Image.open(os.path.join(ASSETS, "logo_48.png")).convert("RGBA")
    small.paste(sl, (3, 3), sl)
    small.save(os.path.join(ASSETS, "wizard_small.bmp"))
    print("icons written to", ASSETS)


if __name__ == "__main__":
    main()
