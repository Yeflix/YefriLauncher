"""
toast.py
----------
Aviso breve dentro de la ventana principal: confirma lo que acaba de
pasar ("Abriendo Blender…", "Quitada de la lista") y, cuando tiene
sentido, ofrece deshacerlo. Aparece sobre el borde inferior de la lista
y se va solo.

Es un widget hijo de la ventana (no una ventana aparte ni un globo de la
bandeja): se ve donde el usuario esta mirando y no roba el foco.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

INFO = "info"
SUCCESS = "success"
ERROR = "error"

_ACCENTS = {
    INFO: QColor(150, 140, 255),
    SUCCESS: QColor(80, 220, 170),
    ERROR: QColor(255, 110, 110),
}

_DEFAULT_MS = 2600
_WITH_ACTION_MS = 6000
_FADE_MS = 160


class Toast(QWidget):
    action_triggered = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self._accent = _ACCENTS[INFO]
        self._on_action = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 10, 8)
        layout.setSpacing(10)

        self._label = QLabel()
        self._label.setStyleSheet("color: white; background: transparent; font-size: 9.5pt;")
        layout.addWidget(self._label, 1)

        self._button = QPushButton()
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._button.setStyleSheet(
            "QPushButton { color: rgb(190, 184, 255); background: transparent; border: none;"
            " font-weight: 600; font-size: 9.5pt; padding: 2px 6px; }"
            "QPushButton:hover { color: white; }"
        )
        self._button.clicked.connect(self._on_button_clicked)
        self._button.hide()
        layout.addWidget(self._button)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

        self.hide()

    def show_message(self, text: str, kind: str = INFO, action_text: str = "",
                     on_action=None, duration_ms: int = 0):
        """Muestra 'text'. Si se pasa action_text + on_action, agrega un
        boton (ej. "Deshacer") que llama a on_action y cierra el aviso.
        Un aviso nuevo reemplaza al que estuviera visible."""
        self._accent = _ACCENTS.get(kind, _ACCENTS[INFO])
        self._label.setText(text)
        self._on_action = on_action if action_text else None
        self._button.setText(action_text)
        self._button.setVisible(bool(action_text and on_action))

        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self.update()

        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

        if not duration_ms:
            duration_ms = _WITH_ACTION_MS if self._on_action else _DEFAULT_MS
        self._timer.start(duration_ms)

    def dismiss(self):
        self._timer.stop()
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def reposition(self):
        """Centrado sobre el borde inferior del area que indique el padre
        (ver MainWindow.toast_area), sin pasarse de su ancho."""
        parent = self.parentWidget()
        if parent is None:
            return
        area = parent.toast_area() if hasattr(parent, "toast_area") else parent.rect()
        width = min(self.sizeHint().width(), max(120, area.width()))
        height = self.sizeHint().height()
        x = area.x() + (area.width() - width) // 2
        y = area.y() + area.height() - height - 10
        self.setGeometry(x, max(area.y(), y), width, height)

    def _on_button_clicked(self):
        callback, self._on_action = self._on_action, None
        self.dismiss()
        self.action_triggered.emit()
        if callback is not None:
            callback()

    def _on_fade_finished(self):
        if self._fade.endValue() == 0.0:
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QColor(255, 255, 255, 40))
        painter.setBrush(QColor(24, 25, 34, 245))
        painter.drawRoundedRect(rect, 9, 9)
        # Barra de acento a la izquierda: el color dice de un vistazo si
        # fue informativo, exito o error.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent)
        painter.drawRoundedRect(6, 8, 3, max(4, self.height() - 16), 1.5, 1.5)
