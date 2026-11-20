"""
virtual_card_list.py
-----------------------
Muestra una lista larga de apps con un pool CHICO de widgets reciclados
(dimensionado a lo que entra en pantalla, no a la cantidad de apps), en
vez de crear una LauncherCard por cada entrada.

La usa MainWindow para las listas grandes y para los resultados de
busqueda grandes (ver _VIRTUALIZE_THRESHOLD en ui/main_window.py). Las
listas chicas siguen el camino de copias reales con scroll en bucle.

Como funciona
---------------
* La lista se aplana en filas de dos tipos y dos alturas: un ENCABEZADO
  por categoria y una fila por app. La posicion de cada fila sale de una
  tabla de offsets acumulados; las filas visibles se ubican con busqueda
  binaria.
* Dos pools independientes: tarjetas y etiquetas de titulo. Solo crecen.
* Asignacion por fila: una fila que sigue visible conserva su widget (y
  su estado de hover). Al hacer scroll solo se reasignan los widgets de
  las filas que salieron, a las que entran. set_groups() reasigna todo:
  los datos pueden haber cambiado aunque la fila sea la misma.
* Los widgets no viven en un layout, asi que cada fila se coloca con el
  ancho actual del contenedor, y un filtro de eventos lo reajusta si ese
  ancho cambia (sin esto quedan con los 640 px por defecto de un widget).
* No hace bucle: al llegar al final, termina.
* El mismo objeto se reusa entre reconstrucciones de la lista mientras
  no cambie la configuracion visual (ver MainWindow._refresh_layout).
"""

from bisect import bisect_left, bisect_right

from PySide6.QtCore import QEvent, QObject

from ui.text_utils import elide_label_text

_HEADER = "header"
_ENTRY = "entry"

# Margen entre el final del texto de un titulo y el borde del contenedor.
_HEADER_RIGHT_MARGIN = 8


class _ResizeFilter(QObject):
    """Avisa cuando el contenedor cambia de tamano. Es hijo del propio
    contenedor: se destruye junto con el."""

    def __init__(self, container, callback):
        super().__init__(container)
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self._callback()
        return False


class VirtualCardList:
    def __init__(self, container, card_factory, header_factory, overscan: int = 6):
        """
        container: QWidget donde viven las filas (el que se le pasa a
            QScrollArea.setWidget(), o un hijo suyo).
        card_factory: funcion sin argumentos -> LauncherCard ya
            configurada y conectada. Se llama una vez por widget del
            pool; el contenido se asigna con LauncherCard.update_entry().
        header_factory: funcion sin argumentos -> QLabel de titulo.
        overscan: filas de margen que se mantienen colocadas por encima
            y por debajo de lo visible.
        """
        self._container = container
        self._card_factory = card_factory
        self._header_factory = header_factory
        self._overscan = max(0, overscan)

        self._rows: list = []            # [(tipo, dato)]
        self._offsets: list = []         # y de inicio de cada fila
        self._index_by_id: dict = {}     # id de entrada -> indice de fila
        self._total_height = 0
        self._card_row_h = 1
        self._header_row_h = 1
        self._card_pool: list = []
        self._header_pool: list = []
        self._placed: dict = {}          # indice de fila -> widget
        self._window = None              # (primera, ultima+1) fila colocada
        self._last_viewport_h = 0
        self._last_scroll = 0

        # Guardado como atributo: un QObject sin referencia en Python
        # puede recolectarse aunque tenga padre en Qt.
        self._resize_filter = _ResizeFilter(container, self._on_container_resized)
        container.installEventFilter(self._resize_filter)

    # ---------- lectura ----------

    @property
    def cards(self):
        """Todas las tarjetas del pool (visibles o no)."""
        return list(self._card_pool)

    @property
    def entry_count(self) -> int:
        return len(self._index_by_id)

    @property
    def total_height(self) -> int:
        return self._total_height

    def row_of(self, entry_id: str):
        """(y, alto) de la fila de esa entrada, o None si no esta."""
        index = self._index_by_id.get(entry_id)
        if index is None:
            return None
        return self._offsets[index], self._card_row_h

    # ---------- carga de datos ----------

    def set_groups(self, groups: list, card_row_height: int, header_row_height: int,
                   viewport_height: int, scroll_value=None):
        """Reemplaza el contenido. groups: [{"title": str, "launchers":
        [entradas]}], ya filtrados y ordenados (los grupos sin apps se
        saltean). Alto de fila = alto del widget + separacion con la
        siguiente. scroll_value: posicion de scroll con la que colocar
        las filas (por defecto, la ultima conocida)."""
        self._card_row_h = max(1, card_row_height)
        self._header_row_h = max(1, header_row_height)

        self._rows = []
        self._offsets = []
        self._index_by_id = {}
        y = 0
        for group in groups:
            launchers = group.get("launchers", [])
            if not launchers:
                continue
            self._offsets.append(y)
            self._rows.append((_HEADER, group.get("title") or group.get("group_id", "")))
            y += self._header_row_h
            for entry in launchers:
                self._index_by_id[entry.get("id")] = len(self._rows)
                self._offsets.append(y)
                self._rows.append((_ENTRY, entry))
                y += self._card_row_h
        self._total_height = y
        self._container.setMinimumHeight(max(1, y))

        if scroll_value is None:
            scroll_value = self._last_scroll
        # Si la lista nueva es mas corta, el scroll anterior puede caer
        # fuera: se coloca como si ya estuviera en el maximo posible.
        scroll_value = min(scroll_value, max(0, y - max(0, viewport_height)))

        self._window = None  # los datos cambiaron: reasignar todo
        self.update_window(scroll_value, viewport_height, force=True)

    # ---------- ventana visible ----------

    def update_window(self, scroll_value: int, viewport_height: int, force: bool = False):
        """Coloca las filas que corresponden al scroll actual. Se llama
        en cada movimiento del scroll: si la ventana de filas no cambio,
        no hace nada."""
        self._last_scroll = max(0, scroll_value)
        self._last_viewport_h = max(0, viewport_height)

        if not self._rows:
            self._placed = {}
            self._window = None
            for widget in self._card_pool + self._header_pool:
                widget.hide()
            return

        margin = self._overscan * self._card_row_h
        y_start = max(0, self._last_scroll - margin)
        y_end = self._last_scroll + self._last_viewport_h + margin

        first = max(0, bisect_right(self._offsets, y_start) - 1)
        last = min(len(self._rows), bisect_left(self._offsets, y_end))
        last = max(last, first + 1)
        if not force and (first, last) == self._window:
            return
        self._window = (first, last)
        self._place_rows(first, last, force)

    def _place_rows(self, first: int, last: int, force: bool):
        if force:
            self._placed = {}
        else:
            for index in [i for i in self._placed if not first <= i < last]:
                del self._placed[index]

        in_use = {id(widget) for widget in self._placed.values()}
        free_cards = [w for w in self._card_pool if id(w) not in in_use]
        free_headers = [w for w in self._header_pool if id(w) not in in_use]

        width = self._container.width()
        for index in range(first, last):
            if index in self._placed:
                continue
            kind, data = self._rows[index]
            if kind == _ENTRY:
                widget = free_cards.pop() if free_cards else self._new(self._card_pool, self._card_factory)
                widget.update_entry(data)
            else:
                widget = free_headers.pop() if free_headers else self._new(self._header_pool, self._header_factory)
                elide_label_text(widget, data, width - _HEADER_RIGHT_MARGIN)
            widget.setGeometry(0, self._offsets[index], width, widget.height())
            widget.show()
            self._placed[index] = widget

        for widget in free_cards + free_headers:
            widget.hide()

    def _new(self, pool: list, factory):
        widget = factory()
        widget.setParent(self._container)
        pool.append(widget)
        return widget

    def _on_container_resized(self):
        """El ancho del contenedor cambio (o recien se conocio): se
        reajusta lo colocado, sin reasignar contenido."""
        width = self._container.width()
        for index, widget in self._placed.items():
            kind, data = self._rows[index]
            if kind == _HEADER:
                elide_label_text(widget, data, width - _HEADER_RIGHT_MARGIN)
            widget.setGeometry(widget.x(), widget.y(), width, widget.height())
