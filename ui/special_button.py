"""
special_button.py
--------------------
Boton especial del PROGRAMA (no es una app del sistema), usado para
"Agregar app" y "Configuracion". Se diferencia de una LauncherCard
comun con un borde de acento en pulso continuo ("respiracion").

El pulso NO corre con un QTimer propio por instancia -- lo maneja un
unico reloj compartido en MainWindow (ver _pulse_tick), que llama a
set_glow_phase() en todos los botones vivos. Con varias copias del
boton (placement "inside" con scroll infinito = 3 copias) esto evita
tener multiples timers latiendo en paralelo sin necesidad, y permite
pausar el pulso globalmente cuando la ventana esta oculta.
"""

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


def _responsive_symbol_pt(height: int) -> int:
    """Mismo criterio que ui.launcher_card._responsive_font_pt: a
    height=50 (el default de siempre) da exactamente 13, igual que el
    valor fijo que habia antes -- ningun usuario que no toque el slider
    de tamano de tarjeta nota diferencia. Antes este boton no escalaba
    en absoluto con 'height' (que SI recibe de compact_card_height, ver
    ui/main_window.py) -- con tarjetas muy compactas el simbolo/texto
    quedaban desproporcionadamente grandes."""
    return max(8, min(13, round(height * 0.26)))


def _responsive_text_pt(height: int) -> float:
    """Igual que _responsive_symbol_pt pero para el texto ('Agregar
    app' / 'Configuracion'), que usa un tamano fraccionario (10.5pt) --
    setPointSizeF() en vez de QSS para que el valor por defecto de
    verdad de 10.5 exacto y no un entero redondeado."""
    return max(7.0, min(10.5, height * 0.21))


class SpecialButton(QWidget):
    clicked = Signal()

    def __init__(self, text: str, symbol: str, accent_color: QColor, height: int = 46, parent=None):
        super().__init__(parent)
        self._accent = accent_color
        self._hover = False
        self._glow_phase = 0.0

        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 0, 15, 0)
        layout.setSpacing(12)

        symbol_label = QLabel(symbol)
        symbol_font = QFont()
        symbol_font.setPointSize(_responsive_symbol_pt(height))
        symbol_font.setBold(True)
        symbol_label.setFont(symbol_font)
        symbol_label.setStyleSheet(f"color: {accent_color.name()};")
        layout.addWidget(symbol_label)
        layout.setAlignment(symbol_label, Qt.AlignmentFlag.AlignVCenter)

        text_label = QLabel(text)
        text_label.setStyleSheet("color: white; font-weight: 600;")
        text_font = text_label.font()
        text_font.setPointSizeF(_responsive_text_pt(height))
        text_label.setFont(text_font)
        layout.addWidget(text_label)
        layout.setAlignment(text_label, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()

    def set_glow_phase(self, phase: float):
        """Llamado desde el reloj central de MainWindow (~30ms)."""
        self._glow_phase = phase
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Respiracion continua del brillo del borde (oscila entre 0.35 y 1.0).
        pulse = 0.35 + 0.65 * ((math.sin(self._glow_phase) + 1) / 2)
        if self._hover:
            pulse = 1.0

        # Fondo oscuro SOLIDO (igual espiritu que las tarjetas normales),
        # no un tinte del color de acento con alpha bajo -- eso se volvia
        # casi invisible (y el texto blanco ilegible) sobre fondos claros
        # detras de la ventana translucida. El acento queda reservado
        # para el borde/simbolo, que es lo que da la identidad especial.
        fill = QColor(20, 21, 30, 235) if not self._hover else QColor(34, 35, 48, 245)

        border = QColor(self._accent)
        border.setAlphaF(pulse)

        painter.setPen(QPen(border, 1.4))
        painter.setBrush(fill)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 8, 8)
        super().paintEvent(event)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        # self.clicked.emit() puede disparar una reconstruccion de la UI que
        # termine destruyendo este mismo widget (aunque se difiera con
        # QTimer.singleShot, es una salvaguarda extra por si algun camino
        # la procesa antes de tiempo). Si ya no existe, no hay nada mas que
        # hacer aqui.
        try:
            super().mouseReleaseEvent(event)
        except RuntimeError:
            pass
