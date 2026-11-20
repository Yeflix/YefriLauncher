"""
app_icon.py
-------------
Genera el icono del programa (bandeja del sistema y .exe) por codigo,
sin depender de un archivo de imagen externo.

El dibujo representa lo que el programa ES: el panel flotante oscuro con
su lista de tarjetas, donde una tarjeta aparece resaltada con el
degradado "spectrum" y corrida hacia un lado -- el mismo efecto de hover
(crece y se desliza) que tiene la lista real.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap

# Mismos colores que el icono anterior: verde-cyan -> celeste -> violeta -> magenta
_SPECTRUM = [
    (0.00, QColor(80, 220, 170)),
    (0.35, QColor(120, 170, 255)),
    (0.70, QColor(150, 140, 255)),
    (1.00, QColor(230, 130, 220)),
]

_PANEL = QColor(12, 13, 20)
_PANEL_BORDER = QColor(255, 255, 255, 28)
_CARD = QColor(255, 255, 255, 50)       # tarjetas en reposo
_CARD_ICON = QColor(255, 255, 255, 60)  # cuadradito de "icono de la app"
_HIGHLIGHT_INDEX = 1                     # cual tarjeta esta en hover


def build_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # --- panel ---
    corner = size * 0.22
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_PANEL)
    p.drawRoundedRect(QRectF(0, 0, size, size), corner, corner)
    if size >= 32:
        p.setPen(QPen(_PANEL_BORDER, max(1.0, size / 64)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = max(0.5, size / 128)
        p.drawRoundedRect(QRectF(inset, inset, size - 2 * inset, size - 2 * inset),
                          corner - inset, corner - inset)

    # --- tarjetas apiladas ---
    rows = 4
    margin = size * 0.15
    gap = size * 0.07
    inner_h = size - 2 * margin
    row_h = (inner_h - gap * (rows - 1)) / rows
    base_w = size - 2 * margin
    slide = size * 0.08  # cuanto se corre la tarjeta resaltada
    show_square = size >= 40

    for i in range(rows):
        y = margin + i * (row_h + gap)
        radius = row_h * 0.42

        if i == _HIGHLIGHT_INDEX:
            # La resaltada "crece" un poco y se desliza, como en el hover real.
            grow = row_h * 0.22
            rect = QRectF(margin + slide, y - grow / 2, base_w - slide + margin * 0.35, row_h + grow)
            grad = QLinearGradient(QPointF(rect.left(), 0), QPointF(rect.right(), 0))
            for pos, color in _SPECTRUM:
                grad.setColorAt(pos, color)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(rect, radius, radius)
            if show_square:
                sq = rect.height() * 0.46
                p.setBrush(QColor(12, 13, 20, 200))
                p.drawRoundedRect(QRectF(rect.left() + rect.height() * 0.28,
                                         rect.center().y() - sq / 2, sq, sq), sq * 0.3, sq * 0.3)
        else:
            rect = QRectF(margin, y, base_w, row_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_CARD)
            p.drawRoundedRect(rect, radius, radius)
            if show_square:
                sq = rect.height() * 0.46
                p.setBrush(_CARD_ICON)
                p.drawRoundedRect(QRectF(rect.left() + rect.height() * 0.28,
                                         rect.center().y() - sq / 2, sq, sq), sq * 0.3, sq * 0.3)

    p.end()
    return QIcon(pixmap)
