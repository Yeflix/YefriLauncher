"""
launcher_card.py
------------------
Una tarjeta de la lista: icono + nombre, con animacion de hover.

* hoverProgress (una sola propiedad animable) mueve a la vez el alto
  visual, el color y el desplazamiento del contenido.
* El "crecimiento" en hover es SOLO visual: el widget reserva siempre el
  alto expandido y se redibuja mas grande dentro de ese espacio. Cambiar
  el tamano real en cada frame recalcularia el layout de toda la lista.
* Imagen de fondo opcional por app: se revela tras un momento de hover
  sostenido. Se carga recien la primera vez que hace falta (no al crear
  la tarjeta) y reducida al tamano maximo en que se va a ver.
* Mini-botones que aparecen en hover: X (quitar de la lista) y flecha
  (abrir el panel ampliado, ver ui/expand_overlay.py).
* Estado "seleccionada" (borde de acento): la tarjeta que abriria Enter
  al navegar con el teclado. Lo decide MainWindow.
* La tarjeta no modifica datos: emite senales y MainWindow actua. Los
  dialogos (elegir imagen, nueva categoria) tambien los abre MainWindow,
  nunca la tarjeta: un dialogo es un bucle de eventos anidado y la
  tarjeta puede destruirse mientras esta abierto.
* update_entry() reutiliza la tarjeta para otra app (pool de la lista
  virtualizada, ver ui/virtual_card_list.py).
"""

import os

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFontMetrics, QImageReader, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QStyle,
    QWidget,
)

_ICON_SIZE = 32
_MIN_ICON_SIZE = 16
_MIN_FONT_PT = 8
_MAX_FONT_PT = 11
_BG_REVEAL_DELAY_MS = 500

_EASING_MAP = {
    "Linear": QEasingCurve.Type.Linear,
    "OutQuad": QEasingCurve.Type.OutQuad,
    "OutCubic": QEasingCurve.Type.OutCubic,
    "OutExpo": QEasingCurve.Type.OutExpo,
    "OutBack": QEasingCurve.Type.OutBack,
    "InOutCubic": QEasingCurve.Type.InOutCubic,
    "InOutQuad": QEasingCurve.Type.InOutQuad,
    "OutElastic": QEasingCurve.Type.OutElastic,
    "OutBounce": QEasingCurve.Type.OutBounce,
    "InOutBack": QEasingCurve.Type.InOutBack,
}

# Las curvas con overshoot/rebote necesitan mas tiempo para sentirse
# fluidas que una curva simple con la MISMA duracion base -- si no, se
# ven cortadas/bruscas. Se multiplica la duracion configurada segun la
# curva elegida.
_DURATION_MULTIPLIER = {
    "OutBack": 1.4,
    "InOutBack": 1.4,
    "OutElastic": 1.9,
    "OutBounce": 1.6,
}

# El flash de click y el revelado del fondo personalizado usan siempre
# OutCubic (asi se ven consistentes entre si, sin depender de la curva
# de easing elegida por el usuario para el hover principal, que puede
# tener rebote/overshoot y no queda bien en un flash tan corto). Pero SI
# deben respetar duration_ms/speed_multiplier -- antes tenian una
# duracion fija (220ms y 400ms) sin importar la configuracion, lo que se
# sentia desincronizado si el usuario elegia animaciones muy rapidas o
# muy lentas. Estas proporciones preservan los valores originales
# (220ms y 400ms) cuando duration_ms esta en su default (220).
_FLASH_DURATION_RATIO = 220 / 220     # = 1.0
_BG_REVEAL_DURATION_RATIO = 400 / 220  # ~= 1.818

# Caches de modulo, compartidos por todas las tarjetas. Con tope (se
# descarta la entrada mas vieja): la app vive semanas en la bandeja.
_MAX_ICON_CACHE = 400
_MAX_BG_CACHE = 24

# Lado mayor, en pixeles, con que se guarda en memoria una imagen de
# fondo. Alcanza para el panel ampliado en una pantalla al 200%; un
# fondo de pantalla 4K entero ocuparia ~33 MB por imagen.
_BG_MAX_SIDE = 1600

_SELECTED_BORDER = QColor(150, 140, 255, 230)
_FAVORITE_STAR = QColor(255, 205, 90)


def _cache_set(cache: dict, key, value, limit: int):
    if len(cache) >= limit:
        del cache[next(iter(cache))]
    cache[key] = value


_bg_image_cache: dict = {}
_icon_pixmap_cache: dict = {}

_FALLBACK_ICON_KEY = "__fallback__"


def _resolve_easing(name: str) -> QEasingCurve.Type:
    return _EASING_MAP.get(name, QEasingCurve.Type.OutCubic)


def _resolve_duration(base_ms: int, easing_name: str, speed_multiplier: float = 1.0) -> int:
    curve_multiplier = _DURATION_MULTIPLIER.get(easing_name, 1.0)
    speed = speed_multiplier if speed_multiplier and speed_multiplier > 0 else 1.0
    return max(30, round(base_ms * curve_multiplier / speed))


def _responsive_icon_size(base_height: int) -> int:
    """El icono nunca crece mas alla de _ICON_SIZE (32px, el tamano de
    siempre para el alto de tarjeta por defecto de 50px), pero se achica
    en tarjetas compactas para no desbordar verticalmente el rectangulo
    de fondo -- que en reposo mide EXACTAMENTE 'base_height' (ver
    _background_rect: el inset por expand_px desaparece del todo en
    hover_progress=0, o sea el momento en que la tarjeta no esta
    hovereada). Se reservan ~14px de aire vertical (7 arriba + 7 abajo)
    y nunca se baja de 16px (mas chico deja de ser reconocible)."""
    return max(_MIN_ICON_SIZE, min(_ICON_SIZE, base_height - 14))


def _responsive_font_pt(base_height: int) -> int:
    """Mismo criterio que _responsive_icon_size pero para el tamano de
    fuente del nombre: en una tarjeta compacta, los 11pt de siempre ya
    no entran comodos en una sola linea vertical -- se interpola
    linealmente contra el alto configurado, con un piso de 8pt (menos
    que eso se vuelve dificil de leer)."""
    return max(_MIN_FONT_PT, min(_MAX_FONT_PT, round(base_height * 0.22)))


def _load_icon_pixmap(entry: dict, size: int = _ICON_SIZE) -> QPixmap:
    icon_path = entry.get("icon")
    has_own_icon = bool(icon_path) and icon_path != "auto" and os.path.exists(icon_path)

    # El icono se pide directamente en resolucion nativa de la pantalla
    # (tamano logico * devicePixelRatio) y se marca con setDevicePixelRatio
    # para que Qt lo dibuje nitido en monitores con escalado (125%, 150%,
    # etc. -- muy comun en Windows). Sin esto, Qt reescala al vuelo un
    # pixmap pensado para 1x y se ve borroso. _load_icon_pixmap es una
    # funcion de modulo (no atada a un widget en particular, porque el
    # cache de iconos se comparte entre todas las tarjetas), asi que se
    # usa la pantalla primaria como referencia -- una simplificacion
    # razonable dado que el cache es compartido entre instancias.
    #
    # 'size' entra en la clave de cache porque con tarjetas compactas
    # (ver LauncherCard._icon_size) el mismo icono se pide en mas de un
    # tamano dentro del mismo proceso (ej. tarjetas normales + la vista
    # previa en vivo de Configuracion, que puede usar otro tamano).
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0

    cache_key = (icon_path if has_own_icon else _FALLBACK_ICON_KEY, dpr, size)
    cached = _icon_pixmap_cache.get(cache_key)
    if cached is not None:
        return cached

    target = max(1, round(size * dpr))
    pix = None
    if has_own_icon:
        loaded = QPixmap(icon_path)
        if not loaded.isNull():
            pix = loaded.scaled(
                target, target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pix.setDevicePixelRatio(dpr)

    if pix is None:
        style = QApplication.instance().style()
        fallback = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        pix = fallback.pixmap(target, target)
        pix.setDevicePixelRatio(dpr)
        cache_key = (_FALLBACK_ICON_KEY, dpr, size)  # si la carga propia fallo, cachear como fallback

    _cache_set(_icon_pixmap_cache, cache_key, pix, _MAX_ICON_CACHE)
    return pix


def _load_bg_pixmap(path: str):
    """Imagen de fondo lista para pintar, o None. Se decodifica ya
    reducida (QImageReader.setScaledSize) si es mas grande que
    _BG_MAX_SIDE: menos memoria y una carga mas rapida."""
    if not path:
        return None
    cached = _bg_image_cache.get(path)
    if cached is not None:
        return cached
    if not os.path.exists(path):
        return None

    reader = QImageReader(path)
    reader.setAutoTransform(True)  # respeta la orientacion EXIF de las fotos
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > _BG_MAX_SIDE:
        reader.setScaledSize(
            size.scaled(_BG_MAX_SIDE, _BG_MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio)
        )
    image = reader.read()
    if image.isNull():
        return None
    pix = QPixmap.fromImage(image)
    _cache_set(_bg_image_cache, path, pix, _MAX_BG_CACHE)
    return pix


class _MiniButton(QWidget):
    """Boton chico y redondo (X o flecha) que solo aparece durante el
    hover. Es un QWidget hijo real (no algo pintado) para que reciba
    su propio click/hover sin disparar el click de la tarjeta."""

    clicked = Signal()
    entered = Signal()

    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self._symbol = symbol
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawEllipse(self.rect())
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._symbol)

    def enterEvent(self, event):
        self.entered.emit()
        super().enterEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()  # no propagar a la tarjeta (padre)


class LauncherCard(QWidget):
    clicked = Signal(str)  # emite entry["id"]
    remove_requested = Signal(str)  # emite entry["id"] al elegir "Quitar de la lista" (menu o boton X)
    background_image_changed = Signal(str, str)  # entry["id"], nueva ruta ("" para quitar)
    background_pick_requested = Signal(str)  # entry["id"] -- "Asignar imagen de fondo..."
    favorite_toggled = Signal(str, bool)  # entry["id"], nuevo estado de favorita
    category_move_requested = Signal(str, str)  # entry["id"], group_id destino (menu "Mover a categoria")
    new_category_requested = Signal(str)  # entry["id"] -- "Nueva categoria..." desde el menu
    expand_requested = Signal(object)  # emite self (la propia tarjeta), al pasar el mouse sobre la flecha
    collapse_requested = Signal()  # al abandonar la tarjeta de verdad

    def __init__(
        self,
        entry: dict,
        base_height: int = 50,
        expand_px: int = 20,
        bg_alpha: int = 220,
        duration_ms: int = 220,
        easing: str = "OutCubic",
        slide_px: int = 0,
        slide_direction: str = "none",  # "right" | "left" | "none"
        slide_mode: str = "content_only",  # "content_only" | "full_card"
        show_tooltip: bool = False,
        arrow_side_preference: str = "right",  # lado del boton de flecha/expandir
        speed_multiplier: float = 1.0,
        parent=None,
    ):
        super().__init__(parent)
        self.entry = entry
        # Callable(entry_id) -> (categorias, group_id_actual), lo asigna
        # MainWindow. None = sin submenu de categorias (ej. la vista previa
        # del panel de Configuracion).
        self.category_provider = None

        self._base_height = base_height
        self._expand_px = expand_px
        self._icon_size = _responsive_icon_size(base_height)
        self._name_font_pt = _responsive_font_pt(base_height)
        self._slide_px = slide_px
        self._slide_direction = slide_direction
        self._slide_mode = slide_mode
        self._base_color = QColor(12, 13, 20, bg_alpha)
        self._hover_color = QColor(46, 50, 74, min(255, bg_alpha + 25))
        self._hover_progress = 0.0

        # El lado de la flecha/expandir SIEMPRE sigue la preferencia
        # configurada (antes seguia la direccion del desplazamiento
        # cuando habia uno, y la preferencia solo aplicaba sin
        # desplazamiento -- generaba confusion porque el control de
        # Configuracion parecia "no hacer nada" la mayoria de las veces).
        self._arrow_side = arrow_side_preference if arrow_side_preference in ("left", "right") else "right"

        # El widget SIEMPRE reserva el alto expandido; "crecer" en hover
        # es puramente visual (ver paintEvent), nunca cambia el tamano
        # real -> el layout de la lista no se recalcula en cada frame.
        self.setFixedHeight(base_height + expand_px)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Se guarda como atributo (no solo se usa una vez aca) porque
        # update_entry() -- el pool reciclado de listas grandes, ver
        # ui/virtual_card_list.py -- necesita saber despues si esta
        # tarjeta debe mostrar tooltip, y no hay forma confiable de
        # inferirlo mirando el tooltip actual (podria estar vacio por el
        # entry de placeholder con el que se crean las tarjetas del pool,
        # sin que eso signifique que show_tooltip sea False).
        self._show_tooltip = show_tooltip
        if show_tooltip:
            self.setToolTip(entry.get("target", ""))

        self._animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._animation.setDuration(_resolve_duration(duration_ms, easing, speed_multiplier))
        self._animation.setEasingCurve(_resolve_easing(easing))

        # Flash breve al hacer click (feedback antes de que el proceso
        # externo termine de abrir, que puede tardar un par de segundos).
        # La curva queda fija en OutCubic (se ve mejor en un flash tan
        # corto que con rebote/overshoot), pero la duracion SI respeta
        # duration_ms/speed_multiplier -- antes eran 220ms fijos sin
        # importar la configuracion de animacion del usuario.
        self._flash_progress = 0.0
        self._flash_animation = QPropertyAnimation(self, b"flashProgress", self)
        self._flash_animation.setDuration(
            _resolve_duration(duration_ms * _FLASH_DURATION_RATIO, "OutCubic", speed_multiplier)
        )
        self._flash_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._flash_animation.setStartValue(1.0)
        self._flash_animation.setEndValue(0.0)

        # Imagen de fondo (opcional). El pixmap se carga la primera vez
        # que hace falta (ver _ensure_bg), no aca: crear una lista no
        # debe decodificar todas las imagenes asignadas.
        self._bg_path = entry.get("hover_background") or ""
        self._bg_pixmap = None
        self._bg_loaded = False
        self._bg_reveal_progress = 0.0
        # _bg_pixmap ya escalado al tamano del widget, para no reescalar
        # en cada frame. Se invalida en resizeEvent.
        self._scaled_bg_cache = None
        self._scaled_bg_dpr = None
        self._selected = False

        self._bg_reveal_timer = QTimer(self)
        self._bg_reveal_timer.setSingleShot(True)
        self._bg_reveal_timer.setInterval(_BG_REVEAL_DELAY_MS)
        self._bg_reveal_timer.timeout.connect(self._start_bg_reveal)

        self._bg_reveal_animation = QPropertyAnimation(self, b"bgRevealProgress", self)
        self._bg_reveal_animation.setDuration(
            _resolve_duration(duration_ms * _BG_REVEAL_DURATION_RATIO, "OutCubic", speed_multiplier)
        )
        self._bg_reveal_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._content = QWidget(self)
        content_layout = QHBoxLayout(self._content)
        content_layout.setContentsMargins(15, 0, 15, 0)
        content_layout.setSpacing(15)

        self._icon_label = QLabel()
        self._icon_label.setPixmap(_load_icon_pixmap(entry, self._icon_size))
        self._icon_label.setFixedSize(self._icon_size, self._icon_size)
        content_layout.addWidget(self._icon_label)
        content_layout.setAlignment(self._icon_label, Qt.AlignmentFlag.AlignVCenter)

        # El nombre completo se guarda aparte porque el texto que
        # termina en el QLabel puede quedar elidido con "..." (ver
        # _update_name_elision) -- entry.get("name") no alcanza para
        # saber si se esta mostrando completo o no.
        self._full_name = entry.get("name") or "Sin nombre"
        self._name_label = QLabel(self._full_name)
        self._name_label.setStyleSheet("color: white; background: transparent;")
        name_font = self._name_label.font()
        name_font.setPointSize(self._name_font_pt)
        self._name_label.setFont(name_font)  # setFont() directo, no via QSS: hace falta
        # que font() devuelva el tamano correcto DE INMEDIATO para que
        # QFontMetrics (_update_name_elision) mida bien -- una fuente
        # aplicada solo por hoja de estilo recien se refleja en
        # .font() cuando Qt hace el primer "polish" del widget, no en
        # el momento de llamar a setStyleSheet().
        content_layout.addWidget(self._name_label)
        content_layout.setAlignment(self._name_label, Qt.AlignmentFlag.AlignVCenter)
        content_layout.addStretch()

        # Mini botones (X / flecha), solo visibles durante el hover.
        self._close_btn = _MiniButton("\u2715", self)
        self._close_btn.clicked.connect(lambda: self.remove_requested.emit(self.entry["id"]))
        self._close_btn.hide()

        arrow_symbol = "\u25B6" if self._arrow_side == "right" else "\u25C0"
        self._expand_btn = _MiniButton(arrow_symbol, self)
        self._expand_btn.entered.connect(lambda: self.expand_requested.emit(self))
        self._expand_btn.hide()

        self._update_name_elision()

    def update_entry(self, entry: dict):
        """Reutiliza esta tarjeta para mostrar una entrada DISTINTA sin
        crear un widget nuevo -- lo usa el pool reciclado de listas
        grandes (ver ui/virtual_card_list.py; listas chicas/medianas
        siguen construyendo una LauncherCard real por app, sin pasar por
        aca). Reinicia el hover y la revelacion de fondo al instante
        (sin animar): la tarjeta esta a punto de reposicionarse para
        mostrar una app distinta, asi que cualquier animacion en curso
        pertenece a la entrada VIEJA y no tiene sentido seguir
        mostrandola sobre la nueva."""
        self.entry = entry

        self._animation.stop()
        self._set_hover_progress(0.0)

        self._flash_animation.stop()
        self._set_flash_progress(0.0)

        self._bg_reveal_timer.stop()
        self._bg_reveal_animation.stop()
        self._bg_path = entry.get("hover_background") or ""
        self._bg_pixmap = None
        self._bg_loaded = False
        self._set_bg_reveal_progress(0.0)
        self._scaled_bg_cache = None
        self._selected = False

        self._icon_label.setPixmap(_load_icon_pixmap(entry, self._icon_size))

        self._full_name = entry.get("name") or "Sin nombre"
        self._name_label.setText(self._full_name)
        self._update_name_elision()

        if self._show_tooltip:
            self.setToolTip(entry.get("target", ""))

        self.update()

    # ---------- propiedades animables ----------

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float):
        self._hover_progress = value
        self._update_content_geometry()
        self._update_mini_buttons_geometry()
        visible = value > 0.4
        self._close_btn.setVisible(visible)
        self._expand_btn.setVisible(visible)
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)

    def _get_flash_progress(self) -> float:
        return self._flash_progress

    def _set_flash_progress(self, value: float):
        self._flash_progress = value
        self.update()

    flashProgress = Property(float, _get_flash_progress, _set_flash_progress)

    def _get_bg_reveal_progress(self) -> float:
        return self._bg_reveal_progress

    def _set_bg_reveal_progress(self, value: float):
        self._bg_reveal_progress = value
        self.update()

    bgRevealProgress = Property(float, _get_bg_reveal_progress, _set_bg_reveal_progress)

    # ---------- geometria interna ----------

    def resizeEvent(self, event):
        self._scaled_bg_cache = None  # el tamano real cambio -> hay que reescalar de nuevo
        self._update_content_geometry()
        self._update_mini_buttons_geometry()
        self._update_name_elision()
        super().resizeEvent(event)

    def _update_name_elision(self):
        """El QLabel del nombre no elide texto por su cuenta: sin esto,
        un nombre largo (frecuente en apps de Microsoft Store, sobre
        todo cuando Get-StartApps no resuelve bien el nombre real -- ver
        core/uwp_detector.py) se corta a lo bruto en el borde del
        widget, sin '...' y a veces solapandose con los mini-botones.

        Se recalcula en cada resize (el ancho real todavia no se conoce
        en __init__: la tarjeta puede no estar en su posicion final de
        layout) reservando SIEMPRE el espacio de un mini-boton -- este
        visible o no en este momento -- para que el texto no cambie de
        tamano/salte cuando los botones aparecen en hover."""
        reserved_for_button = 20 + 6  # ancho de un _MiniButton + su margen
        available = (
            self.width()
            - 15 - 15  # content_layout: margenes izquierdo/derecho
            - self._icon_size
            - 15  # content_layout: spacing entre icono y nombre
            - reserved_for_button
        )
        available = max(20, available)

        fm = QFontMetrics(self._name_label.font())
        elided = fm.elidedText(self._full_name, Qt.TextElideMode.ElideRight, available)
        self._name_label.setText(elided)

        # Qt le da prioridad al tooltip de un widget hijo por sobre el
        # del padre mientras el mouse este encima del hijo -- asi que
        # este tooltip (el nombre completo, cuando quedo truncado) le
        # "tapaba" por completo al tooltip de la tarjeta (la ruta del
        # programa, ver self.setToolTip() en __init__/update_entry,
        # activado por separado con la opcion "Mostrar tooltip con la
        # ruta del programa"): bastaba con que el nombre fuera largo
        # para que esa opcion dejara de notarse en la practica. Si
        # ambos aplican se combinan en vez de que uno tape al otro.
        if elided == self._full_name:
            name_tooltip = ""
        elif self._show_tooltip:
            target = self.entry.get("target", "")
            name_tooltip = f"{self._full_name}\n{target}" if target else self._full_name
        else:
            name_tooltip = self._full_name
        self._name_label.setToolTip(name_tooltip)

    def _content_only_offset_x(self) -> float:
        """Modo actual (por defecto): el contenido se mueve, el fondo no."""
        if self._slide_direction == "right":
            return self._slide_px * self._hover_progress
        elif self._slide_direction == "left":
            return -self._slide_px * self._hover_progress
        return 0.0

    def _full_card_offset_x(self) -> float:
        """Modo alternativo: posicion del borde izquierdo del fondo (y
        del contenido, que se mueve junto con el)."""
        if self._slide_direction == "right":
            return self._slide_px * self._hover_progress          # 0 -> slide_px
        elif self._slide_direction == "left":
            return self._slide_px * (1 - self._hover_progress)    # slide_px -> 0
        return 0.0

    def _update_content_geometry(self):
        if self._slide_mode == "full_card" and self._slide_direction != "none":
            offset = self._full_card_offset_x()
        else:
            offset = self._content_only_offset_x()
        self._content.setGeometry(round(offset), 0, self.width(), self.height())

    def _update_mini_buttons_geometry(self):
        margin = 6
        self._close_btn.move(self.width() - self._close_btn.width() - margin, margin)
        y = (self.height() - self._expand_btn.height()) // 2
        if self._arrow_side == "right":
            x = self.width() - self._expand_btn.width() - margin
        else:
            x = margin
        self._expand_btn.move(x, y)

    # ---------- pintado ----------

    def _current_color(self) -> QColor:
        t = self._hover_progress
        r = self._base_color.red() + (self._hover_color.red() - self._base_color.red()) * t
        g = self._base_color.green() + (self._hover_color.green() - self._base_color.green()) * t
        b = self._base_color.blue() + (self._hover_color.blue() - self._base_color.blue()) * t
        a = self._base_color.alpha() + (self._hover_color.alpha() - self._base_color.alpha()) * t
        return QColor(int(r), int(g), int(b), int(a))

    def _background_rect(self) -> QRect:
        inset_y = round((self._expand_px / 2) * (1 - self._hover_progress))
        top = inset_y
        height = self.height() - 2 * inset_y

        if self._slide_mode == "full_card" and self._slide_direction != "none":
            full_w = self.width()
            visible_w = max(0, full_w - self._slide_px)
            x0 = round(self._full_card_offset_x())
            return QRect(x0, top, visible_w, height)
        return QRect(0, top, self.width(), height)

    def _get_scaled_bg(self):
        """Version de _bg_pixmap ya escalada al tamano REAL (fijo) del
        widget -- se calcula una sola vez y se reusa en cada paintEvent,
        en vez de llamar QPixmap.scaled() con SmoothTransformation en
        cada frame de la animacion de hover (que dispara update() ~cada
        30ms mientras dura). El widget nunca cambia su tamano real en
        hover (ver nota del modulo), asi que esta cache es valida durante
        toda la animacion; el "achicamiento" visual del fondo se resuelve
        solo con el clip_path de _background_rect(), que es barato.

        Se escala a resolucion nativa (tamano logico * devicePixelRatio)
        y se marca con setDevicePixelRatio para que se vea nitido en
        monitores con escalado (HiDPI), en vez de un pixmap 1x que Qt
        reescala al vuelo y se ve borroso."""
        dpr = self.devicePixelRatioF() or 1.0
        if self._scaled_bg_cache is None or self._scaled_bg_dpr != dpr:
            target_w = max(1, round(self.width() * dpr))
            target_h = max(1, round(self.height() * dpr))
            scaled = self._bg_pixmap.scaled(
                target_w, target_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self._scaled_bg_cache = scaled
            self._scaled_bg_dpr = dpr
        return self._scaled_bg_cache

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._background_rect()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._current_color())
        painter.drawRoundedRect(rect, 6, 6)

        if self._bg_pixmap is not None and self._bg_reveal_progress > 0:
            painter.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(QRectF(rect), 6, 6)
            painter.setClipPath(clip_path)
            painter.setOpacity(self._bg_reveal_progress)
            scaled = self._get_scaled_bg()
            # Centrado respecto al widget COMPLETO (no a `rect`, que es
            # el area recortada/inset actual): al ser el mismo pixmap
            # cacheado en cada frame, el clip_path de arriba es lo unico
            # que cambia la porcion visible durante la animacion.
            # OJO: scaled.width()/height() son pixeles de DISPOSITIVO
            # (fisicos); para posicionarlo hay que usar su tamano LOGICO
            # (dividido por su propio devicePixelRatio), que es como
            # QPainter lo va a dibujar realmente.
            scaled_dpr = scaled.devicePixelRatioF() or 1.0
            logical_w = scaled.width() / scaled_dpr
            logical_h = scaled.height() / scaled_dpr
            full_x = (self.width() - logical_w) / 2
            full_y = (self.height() - logical_h) / 2
            painter.drawPixmap(round(full_x), round(full_y), scaled)
            painter.restore()

        if self._flash_progress > 0:
            painter.setOpacity(1.0)
            painter.setBrush(QColor(255, 255, 255, round(120 * self._flash_progress)))
            painter.drawRoundedRect(rect, 6, 6)

        if self._selected:
            painter.setOpacity(1.0)
            painter.setPen(QPen(_SELECTED_BORDER, 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(rect).adjusted(0.8, 0.8, -0.8, -0.8), 6, 6)

        # Marca de favorita, en el hueco que el nombre reserva para los
        # mini-botones. Se desvanece en hover, cuando aparecen ellos.
        star_alpha = 0.9 * (1.0 - self._hover_progress * 2.5)  # ya invisible a 0.4
        if self.entry.get("favorite") and star_alpha > 0:
            star = QColor(_FAVORITE_STAR)
            star.setAlphaF(min(1.0, star_alpha))
            painter.setOpacity(1.0)
            painter.setPen(star)
            font = painter.font()
            font.setPointSize(self._name_font_pt)
            painter.setFont(font)
            painter.drawText(
                QRect(rect.right() - 26, rect.top(), 20, rect.height()),
                Qt.AlignmentFlag.AlignCenter, "\u2605",
            )

        super().paintEvent(event)

    # ---------- interaccion: hover normal ----------

    def enterEvent(self, event):
        self._animate_to(1.0)
        if self._bg_path:
            self._bg_reveal_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # Entrar a un mini-boton hijo (X o flecha) tambien dispara el
        # leaveEvent del padre en Qt, aunque el mouse siga DENTRO del
        # rectangulo de la tarjeta. Si el cursor todavia esta dentro,
        # no es un abandono real -- se ignora (si no, la tarjeta se
        # "des-hoverea" justo al pasar sobre la flecha/X).
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            super().leaveEvent(event)
            return

        self._animate_to(0.0)
        self._bg_reveal_timer.stop()
        self._animate_bg_reveal(0.0)
        self.collapse_requested.emit()
        super().leaveEvent(event)

    def force_unhover_if_stale(self, hovered_widget):
        """Red de seguridad contra hover 'pegado': corrige esta tarjeta
        si esta mostrando estado de hover (visualmente) pero el mouse ya
        no esta realmente ni sobre ella ni sobre sus mini-botones.

        'hovered_widget' es el resultado de
        QApplication.widgetAt(QCursor.pos()) calculado UNA sola vez por
        quien llama (ver MainWindow._resync_all_hover_states) -- es la
        UNICA fuente de verdad confiable aca, porque el problema que
        esto resuelve es precisamente que Qt no siempre entrega un
        leaveEvent real: ni el salto silencioso del scroll infinito
        (bar.setValue() con blockSignals no dispara mousemove) ni una
        reconstruccion completa de la lista (tarjetas viejas destruidas,
        tarjetas nuevas en su lugar, sin que el mouse se haya movido)
        generan ese evento por si solos. Sin esto, una tarjeta podia
        quedar con la animacion de hover activa indefinidamente."""
        if self._hover_progress <= 0.0 and self._bg_reveal_progress <= 0.0:
            return  # ya esta en reposo, nada que corregir

        widget = hovered_widget
        while widget is not None:
            if widget is self:
                return  # de verdad esta hovereada (o lo esta un mini-boton hijo)
            widget = widget.parentWidget()

        self._animate_to(0.0)
        self._bg_reveal_timer.stop()
        self._animate_bg_reveal(0.0)
        self.collapse_requested.emit()

    def _ensure_bg(self):
        """Carga la imagen de fondo la primera vez que hace falta."""
        if not self._bg_loaded:
            self._bg_loaded = True
            self._bg_pixmap = _load_bg_pixmap(self._bg_path)
        return self._bg_pixmap

    def _start_bg_reveal(self):
        if self._ensure_bg() is not None:
            self._animate_bg_reveal(1.0)

    def set_selected(self, selected: bool):
        """Borde de acento: la tarjeta que abriria Enter (navegacion con
        teclado, ver MainWindow)."""
        selected = bool(selected)
        if selected != self._selected:
            self._selected = selected
            self.update()

    def _animate_to(self, target: float):
        self._animation.stop()
        self._animation.setStartValue(self._hover_progress)
        self._animation.setEndValue(target)
        self._animation.start()

    def _animate_bg_reveal(self, target: float):
        self._bg_reveal_animation.stop()
        self._bg_reveal_animation.setStartValue(self._bg_reveal_progress)
        self._bg_reveal_animation.setEndValue(target)
        self._bg_reveal_animation.start()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._flash_animation.stop()
            self._flash_animation.start()
            self.clicked.emit(self.entry["id"])
        try:
            super().mouseReleaseEvent(event)
        except RuntimeError:
            pass

    def trigger_preview(self, hovered: bool):
        """Metodo publico para forzar el estado de hover desde afuera
        (usado por la vista previa en vivo del panel de Configuracion)."""
        self._animate_to(1.0 if hovered else 0.0)

    def get_expand_preview_data(self) -> dict:
        """Datos que necesita MainWindow para dibujar el overlay
        'agrandado fuera de la lista' (ver ui/main_window.py)."""
        return {
            "name": self.entry.get("name", "Sin nombre"),
            "bg_pixmap": self._ensure_bg(),
            "icon_pixmap": self._icon_label.pixmap(),
            "color": self._hover_color,
            "side": self._arrow_side,
        }

    # ---------- menu contextual ----------

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        # Todo se lee de self.entry al abrir el menu: una tarjeta del
        # pool virtualizado se reusa para entradas distintas.
        entry_id = self.entry["id"]
        is_fav = bool(self.entry.get("favorite"))
        fav_action = menu.addAction(
            "Quitar de favoritas" if is_fav else "Marcar como favorita"
        )
        menu.addSeparator()

        # La tarjeta no sabe de categorias: MainWindow le pasa un callable
        # (category_provider) que devuelve (categorias, group_id_actual).
        category_actions = {}
        new_category_action = None
        if self.category_provider is not None:
            categories, current_gid = self.category_provider(entry_id)
            move_menu = menu.addMenu("Mover a categoría")
            for cat in categories:
                action = move_menu.addAction(cat["title"])
                action.setCheckable(True)
                is_current = cat["group_id"] == current_gid
                action.setChecked(is_current)
                action.setEnabled(not is_current)
                category_actions[action] = cat["group_id"]
            move_menu.addSeparator()
            new_category_action = move_menu.addAction("Nueva categoría...")
            menu.addSeparator()

        set_bg_action = menu.addAction("Asignar imagen de fondo...")
        clear_bg_action = menu.addAction("Quitar imagen de fondo") if self._bg_path else None
        menu.addSeparator()
        remove_action = menu.addAction("Quitar de la lista")

        chosen = menu.exec(event.globalPos())
        try:
            menu.deleteLater()
        except RuntimeError:
            return  # la tarjeta (y su menu) se destruyeron con el menu abierto

        if chosen is None:
            return
        try:
            if chosen == fav_action:
                self.favorite_toggled.emit(entry_id, not is_fav)
            elif chosen in category_actions:
                self.category_move_requested.emit(entry_id, category_actions[chosen])
            elif new_category_action is not None and chosen == new_category_action:
                self.new_category_requested.emit(entry_id)
            elif chosen == remove_action:
                self.remove_requested.emit(entry_id)
            elif chosen == set_bg_action:
                self.background_pick_requested.emit(entry_id)
            elif clear_bg_action is not None and chosen == clear_bg_action:
                self.background_image_changed.emit(entry_id, "")
        except RuntimeError:
            pass  # idem: la lista se reconstruyo mientras el menu estaba abierto
