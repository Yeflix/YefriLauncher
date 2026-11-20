"""
make_icon.py
--------------
Genera assets/icons/spectrum.ico (el icono del .exe) a partir del MISMO
dibujo que usa la bandeja (ui/app_icon.py), para que ambos coincidan.

Uso, desde la carpeta del proyecto:

    python tools/make_icon.py

Despues, al compilar con `pyinstaller --noconfirm main.spec`, el .spec lo
detecta solo. Solo hay que correrlo una vez (o cuando cambie el dibujo).
"""

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication

from ui.app_icon import build_app_icon

OUT = os.path.join(ROOT, "assets", "icons", "spectrum.ico")
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main():
    app = QGuiApplication(sys.argv)  # QPixmap necesita una aplicacion Qt viva

    # Se dibuja una sola vez en 256 px y PIL genera el resto de tamanos
    # del .ico (Windows elige el que corresponda segun el contexto).
    pixmap = build_app_icon(256).pixmap(256, 256)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()

    image = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    image.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Icono generado: {OUT}")
    del app


if __name__ == "__main__":
    main()
