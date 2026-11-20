"""
expand_overlay.py
-------------------
El panel ampliado de una tarjeta: una ventana flotante propia (no un
widget hijo, que quedaria recortado por el ancho de la ventana
principal) que se desliza hacia afuera desde el borde de la ventana al
pasar el mouse por la flecha de una tarjeta.

Muestra la imagen de fondo de la app (si tiene), su icono, su nombre y
una linea que dice de donde sale (Steam, Microsoft Store, ruta del
programa). Un clic en el panel abre la app.
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


def describe_entry(entry: dict) -> str:
    """Una linea que dice de donde sale la app."""
    kind = entry.get("type")
    if kind == "steam":
        return "Juego de Steam"
    if kind == "uwp":
        return "App de Microsoft Store"
    target = entry.get("target")
    if isinstance(target, str) and target:
        return target
    return "Agregada a mano" if entry.get("source") == "manual" else ""


class ExpandOverlay(QWidget):
    launch_requested = Signal(str)  # emite entry["id"] al hacer click en el overlay
    mouse_left = Signal()  # el mouse abandono el overlay de verdad

    def __init__(self, owner):
        super().__init__(owner)
        # Aunque tiene 'owner' como parent (para que Qt la destruya sola
        # junto con la ventana principal y la mantenga apilada por
        # encima de ella), Qt.Window la vuelve una ventana top-level de
        # verdad -- ya no queda recortada dentro de los limites de
        # 'owner'.
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._entry_id = ""
        self._name = ""
        self._subtitle = ""
        self._bg_pixmap = None
        self._icon_pixmap = None
        self._color = QColor(46, 50, 74, 235)
        # Version de _bg_pixmap ya escalada al tamano FINAL del overlay
        # (conocido de antemano en show_for_card: la altura es fija
        # durante toda la animacion y el ancho final tambien). Se calcula
        # una sola vez por apertura, en vez de con SmoothTransformation
        # en cada frame de paintEvent mientras el overlay se desliza
        # (geometry-animation de 240ms -> muchos frames).
        self._scaled_bg_cache = None
        self._scaled_bg_target_size = None
        self._scaled_bg_dpr = None

        self._geo_animation = QPropertyAnimation(self, b"geometry", self)
        self._geo_animation.setDuration(240)
        self._geo_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_animation.setDuration(200)
        self._opacity_finished_connected = False

        self.setWindowOpacity(0.0)
        self.hide()

    def show_for_card(self, card, main_window, height_px: int):
        data = card.get_expand_preview_data()
        self._entry_id = card.entry.get("id", "")
        self._name = data["name"]
        self._subtitle = describe_entry(card.entry)
        new_bg_pixmap = data["bg_pixmap"]
        if new_bg_pixmap is not self._bg_pixmap:
            self._scaled_bg_cache = None  # cambio de tarjeta -> invalidar cache anterior
            self._scaled_bg_target_size = None
        self._bg_pixmap = new_bg_pixmap
        self._icon_pixmap = data["icon_pixmap"]
        self._color = data["color"]
        side = data["side"]

        width = card.width()
        card_top_left_global = card.mapToGlobal(card.rect().topLeft())
        main_geo = main_window.frameGeometry()

        # Limites de la pantalla donde esta la ventana: el overlay debe
        # quedar SIEMPRE completo dentro de ellos (sin achicarse), asi
        # que se reposiciona en vez de recortarse.
        screen = main_window.screen() or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None

        y = card_top_left_global.y()
        if screen_geo is not None:
            max_y = screen_geo.bottom() - height_px
            y = max(screen_geo.top(), min(y, max_y))

        if side == "left":
            anchor_x = main_geo.left()
            end_x = anchor_x - width
            if screen_geo is not None:
                end_x = max(end_x, screen_geo.left())
            end_rect = QRect(end_x, y, width, height_px)
            # Ancho 1, NUNCA 0: una ventana translucida (WA_TranslucentBackground)
            # de tamano cero hace fallar UpdateLayeredWindowIndirect en Windows
            # ("uno de los dispositivos... no funciona" es el mensaje generico
            # que da el sistema para ese fallo puntual).
            start_rect = QRect(anchor_x, y, 1, height_px)
        else:
            anchor_x = main_geo.right()
            end_x = anchor_x
            if screen_geo is not None:
                end_x = min(end_x, screen_geo.right() - width)
            end_rect = QRect(end_x, y, width, height_px)
            start_rect = QRect(anchor_x, y, 1, height_px)

        # El ancho FINAL (width, height_px) ya se conoce desde ahora,
        # aunque la ventana arranque en ancho 1 y crezca en 240ms via
        # _geo_animation. Escalar el fondo una sola vez a ese tamano
        # (en vez de en cada frame de paintEvent, con un ancho de rect
        # distinto cada vez) evita repetir SmoothTransformation decenas
        # de veces durante el deslizamiento.
        #
        # Se escala a resolucion nativa (tamano logico * devicePixelRatio)
        # y se marca con setDevicePixelRatio para verse nitido en
        # monitores con escalado (HiDPI).
        dpr = (screen.devicePixelRatio() if screen else None) or 1.0
        target_size = (max(1, width - 2), max(1, height_px - 2))
        if self._bg_pixmap is not None and (
            self._scaled_bg_target_size != target_size or self._scaled_bg_dpr != dpr
        ):
            device_w = max(1, round(target_size[0] * dpr))
            device_h = max(1, round(target_size[1] * dpr))
            scaled = self._bg_pixmap.scaled(
                device_w, device_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self._scaled_bg_cache = scaled
            self._scaled_bg_target_size = target_size
            self._scaled_bg_dpr = dpr

        # Si ya estaba visible (paso de una tarjeta a otra sin salir del
        # todo), arrancamos desde su geometria actual en vez de saltar.
        current_rect = self.geometry() if self.isVisible() else start_rect

        self.setGeometry(current_rect)
        self.show()
        self.raise_()
        self.update()

        self._geo_animation.stop()
        self._geo_animation.setStartValue(current_rect)
        self._geo_animation.setEndValue(end_rect)
        self._geo_animation.start()

        self._fade_to(1.0)

    def hide_animated(self):
        if not self.isVisible():
            return
        self._fade_to(0.0, then_hide=True)

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            if self._entry_id:
                self.launch_requested.emit(self._entry_id)
        super().mouseReleaseEvent(event)

    def _fade_to(self, target: float, then_hide: bool = False):
        if self._opacity_finished_connected:
            self._opacity_animation.finished.disconnect()
            self._opacity_finished_connected = False
        self._opacity_animation.stop()
        self._opacity_animation.setStartValue(self.windowOpacity())
        self._opacity_animation.setEndValue(target)
        if then_hide:
            self._opacity_animation.finished.connect(self.hide)
            self._opacity_finished_connected = True
        self._opacity_animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawRoundedRect(rect, 10, 10)

        if self._bg_pixmap is not None and self._scaled_bg_cache is not None:
            painter.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(QRectF(rect), 10, 10)
            painter.setClipPath(clip_path)
            scaled = self._scaled_bg_cache
            # Centrado respecto al tamano FINAL cacheado (target_size),
            # no respecto a `rect` (que es mas chico mientras el overlay
            # todavia se esta desplegando) -- el clip_path de arriba ya
            # se encarga de no mostrar de mas.
            # OJO: scaled.width()/height() son pixeles de DISPOSITIVO; se
            # usa el tamano LOGICO (dividido por su propio
            # devicePixelRatio) para posicionarlo, que es como QPainter
            # lo dibuja realmente.
            scaled_dpr = scaled.devicePixelRatioF() or 1.0
            logical_w = scaled.width() / scaled_dpr
            logical_h = scaled.height() / scaled_dpr
            x = rect.x() + (self._scaled_bg_target_size[0] - logical_w) / 2
            y = rect.y() + (self._scaled_bg_target_size[1] - logical_h) / 2
            painter.drawPixmap(round(x), round(y), scaled)
            painter.restore()

        # Borde de acento: para que se note claramente que es un
        # elemento flotando por fuera de la ventana, no una tarjeta mas.
        # Se dibuja al final (ver mas abajo) para que quede siempre
        # visible por encima del fondo del titulo.

        if rect.width() < 60:
            painter.setPen(QPen(QColor(150, 140, 255, 200), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 10, 10)
            return  # muy angosto todavia (a mitad del deslizamiento) -- no dibujar texto/icono, se veria cortado

        # Fondo negro al 50% detras del titulo: con imagenes de fondo
        # claras o con mucho detalle, el texto blanco solo no se
        # alcanzaba a leer bien.
        title_bg_rect = QRect(rect.x(), rect.y(), rect.width(), 76)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 128))
        painter.drawRoundedRect(title_bg_rect, 10, 10)
        # Tapar las esquinas inferiores redondeadas del recuadro (para
        # que no se vea como una "pastilla" flotando, sino como un
        # degradado recto de arriba).
        painter.drawRect(title_bg_rect.adjusted(0, title_bg_rect.height() // 2, 0, 0))

        if self._icon_pixmap is not None and not self._icon_pixmap.isNull():
            painter.drawPixmap(rect.x() + 18, rect.y() + 18, self._icon_pixmap)

        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(13)
        font.setBold(True)
        painter.setFont(font)
        text_rect = rect.adjusted(64, 16, -16, -16)
        # drawText no elide por si solo -- un nombre largo se recortaba
        # a lo bruto contra el borde del overlay, sin "...". Mismo
        # criterio que el resto de la app (ver ui/text_utils.py, usado
        # donde el texto vive en un QLabel; aca se dibuja a mano asi que
        # se elide el string antes de pasarlo a drawText).
        name = QFontMetrics(font).elidedText(
            self._name, Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)

        painter.setPen(QColor(255, 255, 255, 140))
        subtitle_font = painter.font()
        subtitle_font.setPointSize(9)
        subtitle_font.setBold(False)
        painter.setFont(subtitle_font)
        subtitle_rect = rect.adjusted(64, 44, -16, -16)
        subtitle = QFontMetrics(subtitle_font).elidedText(
            self._subtitle, Qt.TextElideMode.ElideMiddle, subtitle_rect.width()
        )
        painter.drawText(
            subtitle_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, subtitle
        )

        hint_rect = rect.adjusted(16, 0, -16, -12)
        painter.setPen(QColor(255, 255, 255, 170))
        painter.drawText(
            hint_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, "Clic para abrir"
        )

        painter.setPen(QPen(QColor(150, 140, 255, 200), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 10, 10)
