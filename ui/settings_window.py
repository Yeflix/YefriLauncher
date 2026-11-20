"""
settings_window.py
---------------------
Panel de Configuracion del programa.

Version con navegacion lateral por categorias (General / Deteccion /
Animacion / Botones / Categorias / Apps ocultas / Atajos) sobre un area de contenido
en QStackedWidget, en vez de una unica columna larga con todas las
secciones apiladas una debajo de la otra. El objetivo es que se sienta
como un panel de ajustes "de verdad" (mas cerca de Windows Settings o
las preferencias de un IDE) en vez de un formulario scrolleable: cada
categoria tiene su propio encabezado, y la barra lateral dice de un
vistazo donde esta parado el usuario.

Ajustes de ventana, animacion, deteccion de programas, ubicacion de los
botones especiales, categorias (crear/renombrar/ordenar/eliminar) y
"deshacer" para apps quitadas de la lista,
guardados en config/launchers.json y config/settings.json. Al guardar,
la ventana principal se reconstruye en caliente (sin reiniciar la app).

Incluye una tarjeta de vista previa (pagina "Animacion") que se anima
sola en loop (no hace falta pasar el mouse) para ver el efecto de cada
combinacion de ajustes en tiempo real, antes de guardar.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import auto_categories
from core.config_manager import load_settings, save_settings
from core.scan_worker import start_scan
from ui.category_dialogs import ask_category_name
from ui.launcher_card import LauncherCard

# (texto que ve el usuario, valor real guardado en settings.json)
_EASING_OPTIONS = [
    ("Suave (recomendado)", "OutCubic"),
    ("Rápida", "OutExpo"),
    ("Con rebote", "OutBack"),
    ("Rebote fuerte", "OutBounce"),
    ("Elástica", "OutElastic"),
    ("Suave ida y vuelta", "InOutQuad"),
    ("Con rebote ida y vuelta", "InOutBack"),
    ("Lineal (sin suavizado)", "Linear"),
]

_PLACEMENT_OPTIONS = [
    ("Fuera de la lista", "outside"),
    ("Dentro de la lista", "inside"),
    ("Ocultos", "hidden"),
]

_SLIDE_OPTIONS = [
    ("Hacia la derecha", "right"),
    ("Hacia la izquierda", "left"),
    ("Sin desplazamiento", "none"),
]

_SLIDE_MODE_OPTIONS = [
    ("Solo icono y texto (actual)", "content_only"),
    ("Tarjeta completa (fondo + contenido)", "full_card"),
]

_SORT_OPTIONS = [
    ("Favoritas primero, luego alfabético", "favorites_first"),
    ("Alfabético", "alphabetical"),
    ("Orden de detección (sin ordenar)", "none"),
]

_ARROW_SIDE_OPTIONS = [
    ("Derecha", "right"),
    ("Izquierda", "left"),
]

# Presets en vez de un widget de "presiona una tecla" -- mucho mas
# simple de implementar bien, y cubre los combos mas comunes para esto.
# El primer valor es el que ya trae la app por defecto.
_HOTKEY_OPTIONS = [
    ("Ctrl + Alt + Espacio (por defecto)", "ctrl+alt+space"),
    ("Ctrl + Alt + L", "ctrl+alt+l"),
    ("Ctrl + Shift + Espacio", "ctrl+shift+space"),
    ("Ctrl + Shift + L", "ctrl+shift+l"),
    ("Ctrl + Alt + F1", "ctrl+alt+f1"),
]

_PREVIEW_ENTRY = {"id": "preview", "name": "Vista previa", "icon": "auto", "target": ""}
_PREVIEW_TOGGLE_MS = 900

_NAV_PAGES = ["General", "Detección", "Animación", "Botones", "Categorías", "Apps ocultas", "Atajos"]

# Plantilla: _shortcuts_html() la completa con la etiqueta del atajo
# global que este elegido en el combo, para que la ayuda no mienta.
_SHORTCUTS_HTML_TEMPLATE = (
    "<b>Ventana</b><br>"
    "&bull; <b>{hotkey}</b> (global, funciona aunque el launcher no tenga "
    "el foco): muestra u oculta la ventana<br>"
    "&bull; <b>Escape</b>: limpia la búsqueda; sin búsqueda, oculta la ventana<br>"
    "&bull; <b>Ctrl+Shift+S</b>: abre Configuración (funciona aunque los "
    "botones estén ocultos)<br>"
    "&bull; <b>Arrastrar</b> desde cualquier parte: mueve la ventana "
    "(la posición se recuerda)<br>"
    "&bull; <b>Clic en el icono de la bandeja</b>: abre el menú "
    "(Mostrar/Ocultar, Configuración, Abrir carpeta de datos, Cerrar)<br><br>"
    "<b>Búsqueda y teclado</b><br>"
    "&bull; Al mostrarse la ventana ya se puede escribir para buscar. "
    "No hacen falta acentos ni mayúsculas; valen varias palabras, "
    "siglas (\"vsc\") y el nombre del ejecutable<br>"
    "&bull; <b>Enter</b>: abre la app seleccionada (al buscar, el mejor resultado)<br>"
    "&bull; <b>Flechas arriba/abajo</b> y <b>Re Pág/Av Pág</b>: cambian la selección<br><br>"
    "<b>Sobre una app</b><br>"
    "&bull; <b>Clic</b>: abrirla<br>"
    "&bull; <b>Clic derecho</b>: favorita, mover a categoría, imagen de "
    "fondo, quitar de la lista<br>"
    "&bull; <b>Botón X (al pasar el mouse)</b>: quitar de la lista "
    "(se puede deshacer desde el aviso)<br>"
    "&bull; <b>Botón de flecha (al pasar el mouse)</b>: panel ampliado"
)


def _shortcuts_html(hotkey_label: str) -> str:
    return _SHORTCUTS_HTML_TEMPLATE.format(hotkey=hotkey_label)

# Estilo "formal": fondo neutro grafito, un unico acento (violeta,
# heredado del resto de la app) usado con moderacion, y divisores finos
# en vez de QGroupBox anidados -- la jerarquia ahora la da la barra
# lateral + el titulo de cada pagina, no una caja dentro de otra caja.
_DIALOG_QSS = """
QDialog {
    background-color: rgb(22, 23, 30);
}
QWidget#headerBar, QWidget#sidebar, QWidget#footerBar {
    background-color: rgb(17, 18, 24);
}
QWidget#headerBar {
    border-bottom: 1px solid rgba(255, 255, 255, 18);
}
QWidget#sidebar {
    border-right: 1px solid rgba(255, 255, 255, 18);
}
QWidget#footerBar {
    border-top: 1px solid rgba(255, 255, 255, 18);
}
QWidget#contentArea {
    background-color: rgb(22, 23, 30);
}
QLabel {
    color: rgba(255, 255, 255, 220);
    background: transparent;
}
QLabel#appTitle {
    color: white;
    font-size: 13pt;
    font-weight: 600;
}
QLabel#appSubtitle {
    color: rgba(255, 255, 255, 120);
    font-size: 8pt;
}
QLabel#pageTitle {
    color: white;
    font-size: 13pt;
    font-weight: 600;
}
QLabel#pageCaption {
    color: rgba(255, 255, 255, 135);
    font-size: 9pt;
}
QLabel#sectionTitle {
    color: rgb(178, 170, 255);
    font-size: 9pt;
    font-weight: 600;
}
QLabel#footerNote {
    color: rgba(255, 255, 255, 110);
    font-size: 8pt;
}
QLabel#statusNote {
    color: rgb(150, 140, 255);
    font-size: 8pt;
}
QFrame#sectionDivider {
    background-color: rgba(255, 255, 255, 24);
    max-height: 1px;
    border: none;
}
QListWidget#navList {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 10px 8px;
    font-size: 10pt;
}
QListWidget#navList::item {
    color: rgba(255, 255, 255, 175);
    padding: 10px 12px;
    border-radius: 7px;
    margin-bottom: 2px;
}
QListWidget#navList::item:selected {
    background-color: rgba(150, 140, 255, 40);
    color: white;
    font-weight: 600;
}
QListWidget#navList::item:hover:!selected {
    background-color: rgba(255, 255, 255, 14);
}
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255, 255, 255, 35);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
    background: rgb(150, 140, 255);
}
QComboBox, QListWidget {
    background-color: rgb(32, 33, 43);
    color: white;
    border: 1px solid rgba(255, 255, 255, 35);
    border-radius: 6px;
    padding: 4px 8px;
}
QComboBox QAbstractItemView {
    background-color: rgb(28, 29, 38);
    color: white;
    selection-background-color: rgb(90, 80, 200);
    selection-color: white;
}
QListWidget#hiddenList::item, QListWidget#categoryList::item {
    padding: 4px 6px;
    border-radius: 4px;
}
QListWidget#hiddenList::item:selected, QListWidget#categoryList::item:selected {
    background-color: rgb(90, 80, 200);
    color: white;
}
QListWidget#hiddenList::item:hover, QListWidget#categoryList::item:hover {
    background-color: rgba(255, 255, 255, 25);
}
QCheckBox {
    color: rgba(255, 255, 255, 220);
    spacing: 8px;
}
QPushButton {
    background-color: rgba(255, 255, 255, 22);
    color: white;
    border: 1px solid rgba(255, 255, 255, 45);
    border-radius: 6px;
    padding: 7px 16px;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 40);
}
QPushButton#primaryButton {
    background-color: rgb(120, 108, 230);
    border: none;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: rgb(134, 122, 240);
}
QScrollArea {
    border: none;
    background: transparent;
}
"""


def _build_combo(options):
    combo = QComboBox()
    for label, _value in options:
        combo.addItem(label)
    return combo


def _select_by_value(combo: QComboBox, options, current_value):
    for i, (_label, value) in enumerate(options):
        if value == current_value:
            combo.setCurrentIndex(i)
            return
    combo.setCurrentIndex(0)


def _value_of(combo: QComboBox, options):
    return options[combo.currentIndex()][1]


def _slider_row(label_text: str, slider: QSlider, suffix: str = "") -> QWidget:
    """Fila con el slider + una etiqueta que muestra el valor en vivo."""
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)

    value_label = QLabel(f"{slider.value()}{suffix}")
    value_label.setMinimumWidth(48)
    value_label.setStyleSheet("color: rgb(150, 140, 255); font-weight: 600;")
    slider.valueChanged.connect(lambda v: value_label.setText(f"{v}{suffix}"))

    row_layout.addWidget(slider, stretch=1)
    row_layout.addWidget(value_label)
    return row


def _multiplier_slider_row(slider: QSlider) -> QWidget:
    """Como _slider_row, pero muestra el valor como multiplicador
    (ej. 'x1.0', 'x0.5') en vez de un numero + sufijo."""
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)

    value_label = QLabel(f"x{slider.value() / 100:.1f}")
    value_label.setMinimumWidth(48)
    value_label.setStyleSheet("color: rgb(150, 140, 255); font-weight: 600;")
    slider.valueChanged.connect(lambda v: value_label.setText(f"x{v / 100:.1f}"))

    row_layout.addWidget(slider, stretch=1)
    row_layout.addWidget(value_label)
    return row


def _make_page(title: str, description: str = "") -> tuple:
    """Crea una pagina de contenido con encabezado consistente (titulo +
    descripcion opcional). Devuelve (pagina, layout) para que el
    llamador siga agregando secciones/filas debajo del encabezado."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(18)

    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    layout.addWidget(heading)

    if description:
        caption = QLabel(description)
        caption.setObjectName("pageCaption")
        caption.setWordWrap(True)
        layout.addWidget(caption)

    return page, layout


def _make_section(title: str) -> tuple:
    """Sub-seccion dentro de una pagina: titulo chico + linea divisoria
    fina + un QFormLayout debajo para las filas de esa seccion. El
    equivalente "plano" a lo que antes era un QGroupBox -- sin caja
    propia, porque ya no hace falta anidar cajas dentro de la pagina."""
    wrapper = QWidget()
    outer = QVBoxLayout(wrapper)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(8)

    label = QLabel(title)
    label.setObjectName("sectionTitle")
    outer.addWidget(label)

    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.HLine)
    divider.setObjectName("sectionDivider")
    outer.addWidget(divider)

    form = QFormLayout()
    form.setSpacing(10)
    form.setContentsMargins(0, 4, 0, 0)
    outer.addLayout(form)

    return wrapper, form


class SettingsWindow(QDialog):
    def __init__(self, launcher_manager, parent=None):
        super().__init__(parent)
        self.launcher_manager = launcher_manager
        self.setWindowTitle("Configuración - SPECTRUM Launcher")
        self.setModal(True)
        self.resize(720, 580)
        self.setMinimumSize(620, 480)
        self.setStyleSheet(_DIALOG_QSS)

        self._settings = load_settings()
        win_cfg = self._settings.get("window", {})
        anim_cfg = self._settings.get("animation", {})
        buttons_cfg = self._settings.get("buttons", {})
        detection_cfg = self._settings.get("detection", {})

        # ---- controles: apariencia (pagina General) ----
        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(80, 255)
        self._alpha_slider.setValue(win_cfg.get("background_alpha", 220))

        # Antes "window.width" solo se leia una vez al arrancar la app
        # (ui/main_window.py __init__) y no tenia ningun control en esta
        # ventana -- cambiarlo requeria editar config/settings.json a
        # mano. _apply_window_width() (en main_window.py) lo aplica en
        # caliente al guardar, igual que el resto de esta pagina.
        self._width_slider = QSlider(Qt.Orientation.Horizontal)
        self._width_slider.setRange(260, 600)
        self._width_slider.setValue(win_cfg.get("width", 380))

        self._always_on_top_check = QCheckBox("Siempre visible (always on top)")
        self._always_on_top_check.setChecked(win_cfg.get("always_on_top", True))

        self._tooltips_check = QCheckBox("Mostrar tooltip con la ruta del programa al pasar el mouse")
        self._tooltips_check.setChecked(win_cfg.get("show_tooltips", False))

        self._card_height_slider = QSlider(Qt.Orientation.Horizontal)
        self._card_height_slider.setRange(32, 80)
        self._card_height_slider.setValue(win_cfg.get("compact_card_height", 50))

        self._sort_combo = _build_combo(_SORT_OPTIONS)
        _select_by_value(self._sort_combo, _SORT_OPTIONS,
                         win_cfg.get("sort_mode", "favorites_first"))

        self._hotkey_combo = _build_combo(_HOTKEY_OPTIONS)
        _select_by_value(
            self._hotkey_combo, _HOTKEY_OPTIONS,
            self._settings.get("hotkey_toggle", "ctrl+alt+space"),
        )
        # La pagina "Atajos" (_build_shortcuts_page) muestra este atajo
        # en su texto de ayuda -- se mantiene en sincrono mientras el
        # usuario cambia el combo, antes incluso de guardar, igual que
        # _rebuild_preview reacciona a los otros combos de esta misma
        # ventana.
        self._hotkey_combo.currentIndexChanged.connect(self._update_shortcuts_help)

        # ---- controles: deteccion (pagina Deteccion) ----
        self._scan_steam_check = QCheckBox("Juegos de Steam")
        self._scan_steam_check.setChecked(detection_cfg.get("scan_steam", True))

        self._scan_shortcuts_check = QCheckBox("Accesos directos (Menú Inicio y Escritorio)")
        self._scan_shortcuts_check.setChecked(detection_cfg.get("scan_shortcuts", True))

        self._scan_uwp_check = QCheckBox("Apps de Microsoft Store (UWP)")
        self._scan_uwp_check.setChecked(detection_cfg.get("scan_uwp", True))

        self._auto_scan_check = QCheckBox("Buscar programas nuevos automáticamente al iniciar")
        self._auto_scan_check.setChecked(detection_cfg.get("auto_scan_on_launch", True))

        self._rescan_status = QLabel("")
        self._rescan_status.setObjectName("statusNote")

        # ---- controles: animacion ----
        self._duration_slider = QSlider(Qt.Orientation.Horizontal)
        self._duration_slider.setRange(80, 600)
        self._duration_slider.setValue(anim_cfg.get("duration_ms", 220))

        self._expand_slider = QSlider(Qt.Orientation.Horizontal)
        self._expand_slider.setRange(0, 80)
        self._expand_slider.setValue(anim_cfg.get("hover_expand_px", 34))

        self._easing_combo = _build_combo(_EASING_OPTIONS)
        _select_by_value(self._easing_combo, _EASING_OPTIONS, anim_cfg.get("easing", "OutCubic"))

        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(50, 200)
        self._speed_slider.setValue(round(anim_cfg.get("speed_multiplier", 1.0) * 100))

        # ---- controles: desplazamiento en hover ----
        self._slide_combo = _build_combo(_SLIDE_OPTIONS)
        _select_by_value(
            self._slide_combo, _SLIDE_OPTIONS, anim_cfg.get("hover_slide_direction", "right")
        )

        self._slide_px_slider = QSlider(Qt.Orientation.Horizontal)
        self._slide_px_slider.setRange(0, 40)
        self._slide_px_slider.setValue(anim_cfg.get("hover_slide_px", 14))

        self._slide_mode_combo = _build_combo(_SLIDE_MODE_OPTIONS)
        _select_by_value(
            self._slide_mode_combo, _SLIDE_MODE_OPTIONS, anim_cfg.get("hover_slide_mode", "content_only")
        )

        self._arrow_side_combo = _build_combo(_ARROW_SIDE_OPTIONS)
        _select_by_value(
            self._arrow_side_combo, _ARROW_SIDE_OPTIONS, anim_cfg.get("arrow_side_preference", "right")
        )

        self._expand_height_slider = QSlider(Qt.Orientation.Horizontal)
        self._expand_height_slider.setRange(100, 500)
        self._expand_height_slider.setValue(anim_cfg.get("expand_overlay_height_px", 220))

        # ---- controles: botones especiales ----
        self._placement_combo = _build_combo(_PLACEMENT_OPTIONS)
        _select_by_value(
            self._placement_combo,
            _PLACEMENT_OPTIONS,
            buttons_cfg.get("special_buttons_placement", "outside"),
        )

        # ================= layout general: header / sidebar+contenido / footer =================
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._nav_list = QListWidget()
        self._nav_list.setObjectName("navList")
        self._nav_list.setFixedWidth(190)
        self._nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for page_name in _NAV_PAGES:
            self._nav_list.addItem(QListWidgetItem(page_name))

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 8, 0, 8)
        sidebar_layout.addWidget(self._nav_list)

        self._stack = QStackedWidget()
        self._stack.setObjectName("contentArea")
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_detection_page())
        self._stack.addWidget(self._build_animation_page())
        self._stack.addWidget(self._build_buttons_page())
        self._stack.addWidget(self._build_categories_page())
        self._stack.addWidget(self._build_hidden_page())
        self._stack.addWidget(self._build_shortcuts_page())

        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setWidget(self._stack)
        content_scroll.viewport().setStyleSheet("background-color: rgb(22, 23, 30);")

        self._nav_list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav_list.setCurrentRow(0)

        body.addWidget(sidebar)
        body.addWidget(content_scroll, stretch=1)
        outer.addLayout(body, stretch=1)

        outer.addWidget(self._build_footer())

        # Reconstruir la vista previa cada vez que cambia algo que la afecta.
        self._duration_slider.valueChanged.connect(self._rebuild_preview)
        self._expand_slider.valueChanged.connect(self._rebuild_preview)
        self._alpha_slider.valueChanged.connect(self._rebuild_preview)
        self._easing_combo.currentIndexChanged.connect(self._rebuild_preview)
        self._speed_slider.valueChanged.connect(self._rebuild_preview)
        self._slide_combo.currentIndexChanged.connect(self._rebuild_preview)
        self._slide_px_slider.valueChanged.connect(self._rebuild_preview)
        self._slide_mode_combo.currentIndexChanged.connect(self._rebuild_preview)
        self._arrow_side_combo.currentIndexChanged.connect(self._rebuild_preview)
        self._card_height_slider.valueChanged.connect(self._rebuild_preview)

        self._preview_card = None
        self._preview_state = False
        self._rebuild_preview()

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._toggle_preview)
        self._preview_timer.start(_PREVIEW_TOGGLE_MS)

    # ---------- construccion: header / footer ----------

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(28, 0, 28, 0)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Configuración")
        title.setObjectName("appTitle")
        subtitle = QLabel("SPECTRUM Launcher")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)

        layout.addLayout(titles)
        layout.addStretch()
        return header

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footerBar")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(28, 14, 28, 14)

        note = QLabel("Los cambios se aplican de inmediato al guardar, sin reiniciar el launcher.")
        note.setObjectName("footerNote")
        note.setWordWrap(True)
        layout.addWidget(note, stretch=1)

        # Guardados como atributos para poder deshabilitarlos mientras
        # haya un rescan en background corriendo (ver _on_rescan_clicked
        # mas abajo): cerrar el dialogo a mitad de un escaneo dejaria el
        # QThread corriendo contra una SettingsWindow ya destruida.
        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Guardar")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._on_save)

        layout.addWidget(self._cancel_btn)
        layout.addWidget(self._save_btn)
        return footer

    # ---------- construccion: paginas ----------

    def _build_general_page(self) -> QWidget:
        page, layout = _make_page(
            "General", "Apariencia de la ventana y comportamiento básico del launcher."
        )

        appearance, form = _make_section("Apariencia")
        form.addRow("Opacidad del fondo:", _slider_row("", self._alpha_slider))
        form.addRow("Ancho de la ventana:", _slider_row("", self._width_slider, " px"))
        form.addRow(self._always_on_top_check)
        form.addRow(self._tooltips_check)
        layout.addWidget(appearance)

        cards, cards_form = _make_section("Tarjetas de programas")
        cards_form.addRow("Orden de la lista:", self._sort_combo)
        sort_hint = QLabel(
            "Marca una app como favorita con clic derecho sobre ella para "
            "fijarla arriba de la lista."
        )
        sort_hint.setObjectName("pageCaption")
        sort_hint.setWordWrap(True)
        cards_form.addRow(sort_hint)
        cards_form.addRow("Alto de cada tarjeta:", _slider_row("", self._card_height_slider, " px"))
        cards_hint = QLabel(
            "Tarjetas más chicas achican también el icono y la letra para que "
            "sigan entrando cómodas — útil para que quepan más apps en pantalla "
            "a la vez sin scrollear tanto."
        )
        cards_hint.setObjectName("pageCaption")
        cards_hint.setWordWrap(True)
        cards_form.addRow(cards_hint)
        layout.addWidget(cards)

        layout.addStretch()
        return page

    def _build_detection_page(self) -> QWidget:
        page, layout = _make_page(
            "Detección de programas",
            "Qué fuentes revisa el launcher para armar la lista, y cuándo.",
        )

        sources, form = _make_section("Fuentes")
        form.addRow(self._scan_steam_check)
        form.addRow(self._scan_shortcuts_check)
        form.addRow(self._scan_uwp_check)
        uwp_hint = QLabel(
            "Requiere Windows PowerShell (incluido por defecto en Windows 10/11)."
        )
        uwp_hint.setObjectName("pageCaption")
        uwp_hint.setWordWrap(True)
        form.addRow(uwp_hint)
        layout.addWidget(sources)

        behavior, behavior_form = _make_section("Comportamiento")
        behavior_form.addRow(self._auto_scan_check)
        layout.addWidget(behavior)

        manual, manual_form = _make_section("Acción manual")
        rescan_row = QHBoxLayout()
        self._rescan_btn = QPushButton("Buscar de nuevo ahora")
        self._rescan_btn.clicked.connect(self._on_rescan_clicked)
        rescan_row.addWidget(self._rescan_btn)
        rescan_row.addWidget(self._rescan_status, stretch=1)
        manual_form.addRow(rescan_row)
        layout.addWidget(manual)

        layout.addStretch()
        return page

    def _build_animation_page(self) -> QWidget:
        page, layout = _make_page(
            "Animación", "Cómo reaccionan las tarjetas al pasar el mouse por encima."
        )

        movement, form = _make_section("Movimiento")
        form.addRow("Duración base:", _slider_row("", self._duration_slider, " ms"))
        form.addRow("Cuánto crece en hover:", _slider_row("", self._expand_slider, " px"))
        form.addRow("Curva de animación:", self._easing_combo)
        form.addRow(
            "Velocidad (algunas curvas van rápido/lento distinto):",
            _multiplier_slider_row(self._speed_slider),
        )
        layout.addWidget(movement)

        slide, slide_form = _make_section("Desplazamiento en hover")
        slide_form.addRow("Dirección:", self._slide_combo)
        slide_form.addRow("Cantidad:", _slider_row("", self._slide_px_slider, " px"))
        slide_form.addRow("Qué se desplaza:", self._slide_mode_combo)
        slide_form.addRow("Lado de la flecha / expandir:", self._arrow_side_combo)
        slide_form.addRow(
            "Alto del agrandado (fuera de la lista):",
            _slider_row("", self._expand_height_slider, " px"),
        )
        layout.addWidget(slide)

        preview_wrapper, _unused = _make_section("Vista previa (se anima sola)")
        self._preview_holder = QVBoxLayout()
        preview_wrapper.layout().addLayout(self._preview_holder)
        layout.addWidget(preview_wrapper)

        layout.addStretch()
        return page

    def _build_buttons_page(self) -> QWidget:
        page, layout = _make_page(
            "Botones especiales",
            "Ubicación de los botones 'Agregar app' y 'Configuración' dentro de la ventana.",
        )

        placement, form = _make_section("Ubicación")
        form.addRow("Botones especiales:", self._placement_combo)
        layout.addWidget(placement)
        layout.addStretch()
        return page

    def _build_hidden_page(self) -> QWidget:
        page, layout = _make_page(
            "Apps quitadas de la lista",
            "Restaura una app que hayas quitado con clic derecho o el botón X.",
        )

        self._hidden_list = QListWidget()
        self._hidden_list.setObjectName("hiddenList")
        self._hidden_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._hidden_list.setMaximumHeight(220)
        layout.addWidget(self._hidden_list)

        restore_btn = QPushButton("Restaurar seleccionadas")
        restore_btn.clicked.connect(self._on_restore_selected)
        layout.addWidget(restore_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._reload_hidden_list()
        layout.addStretch()
        return page

    def _build_categories_page(self) -> QWidget:
        page, layout = _make_page(
            "Categorías",
            "Agrupa tus apps en secciones de la lista. Para mover una app, clic derecho "
            "sobre su tarjeta → Mover a categoría. La lista de categorías se edita al "
            "momento (no depende de Guardar); la categorización automática de abajo "
            "se aplica al Guardar.",
        )

        self._category_list = QListWidget()
        self._category_list.setObjectName("categoryList")
        self._category_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._category_list.setMaximumHeight(240)
        self._category_list.currentRowChanged.connect(self._update_category_buttons)
        layout.addWidget(self._category_list)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._cat_new_btn = QPushButton("Nueva...")
        self._cat_rename_btn = QPushButton("Renombrar...")
        self._cat_delete_btn = QPushButton("Eliminar")
        self._cat_up_btn = QPushButton("Subir")
        self._cat_down_btn = QPushButton("Bajar")
        self._cat_new_btn.clicked.connect(self._on_category_new)
        self._cat_rename_btn.clicked.connect(self._on_category_rename)
        self._cat_delete_btn.clicked.connect(self._on_category_delete)
        self._cat_up_btn.clicked.connect(lambda: self._on_category_move(-1))
        self._cat_down_btn.clicked.connect(lambda: self._on_category_move(+1))
        for btn in (self._cat_new_btn, self._cat_rename_btn, self._cat_delete_btn,
                    self._cat_up_btn, self._cat_down_btn):
            buttons.addWidget(btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        note = QLabel(
            "Las apps nuevas que no encajen en una regla automática van a la categoría "
            "por defecto. Al eliminar una categoría, sus apps no se borran: vuelven a la "
            "categoría por defecto. Las categorías vacias no se muestran en la lista."
        )
        note.setObjectName("pageCaption")
        note.setWordWrap(True)
        layout.addWidget(note)

        auto_section, auto_form = _make_section("Categorización automática")
        enabled = auto_categories.enabled_from_settings(self._settings)
        self._auto_rule_checks = {}
        for rule in auto_categories.RULES:
            # Antes el titulo y la descripcion de la regla iban juntos
            # en una sola linea de texto del QCheckBox (f"{title}:
            # {description}") -- QCheckBox, a diferencia de QLabel, no
            # tiene wordWrap: con descripciones largas (la de "Juegos"
            # anda por los 90 caracteres, la de "Microsoft Store" por
            # los 110) el texto quedaba cortado a lo bruto contra el
            # ancho minimo del dialogo (620px, ver setMinimumSize mas
            # arriba), sin forma de leerlo completo salvo agrandando la
            # ventana a mano. Se separa en dos lineas, como ya se hace
            # en esta misma pagina para 'auto_hint'/'note': el checkbox
            # solo lleva el titulo (corto, nunca se corta) y la
            # descripcion va debajo en un QLabel con wordWrap.
            check = QCheckBox(rule.title)
            check.setChecked(rule.rule_id in enabled)
            check.setToolTip(
                f"Manda a la categoría '{rule.title}' las apps detectadas que encajen, "
                "salvo las que ya hayas movido a mano."
            )
            self._auto_rule_checks[rule.rule_id] = check
            auto_form.addRow(check)

            desc = QLabel(rule.description)
            desc.setObjectName("pageCaption")
            desc.setWordWrap(True)
            desc.setContentsMargins(24, 0, 0, 6)  # alineado bajo el texto del checkbox
            auto_form.addRow(desc)
        auto_hint = QLabel(
            "Solo mueve apps detectadas que sigan en la categoría por defecto y que no "
            "hayas movido tú a mano. Desactivar una regla no devuelve lo ya movido. Si "
            "eliminas una de estas categorías, no se vuelve a crear sola."
        )
        auto_hint.setObjectName("pageCaption")
        auto_hint.setWordWrap(True)
        auto_form.addRow(auto_hint)
        layout.addWidget(auto_section)

        self._reload_category_list()
        layout.addStretch()
        return page

    def _build_shortcuts_page(self) -> QWidget:
        page, layout = _make_page("Atajos y controles")

        global_hotkey, form = _make_section("Atajo global (mostrar/ocultar)")
        form.addRow("Combinación:", self._hotkey_combo)
        hotkey_hint = QLabel(
            "Funciona en cualquier momento, aunque el launcher no tenga el foco. "
            "Si no responde, puede que otro programa ya esté usando esa combinación."
        )
        hotkey_hint.setObjectName("pageCaption")
        hotkey_hint.setWordWrap(True)
        form.addRow(hotkey_hint)
        layout.addWidget(global_hotkey)

        self._shortcuts_label = QLabel(_shortcuts_html(self._hotkey_combo.currentText()))
        self._shortcuts_label.setWordWrap(True)
        self._shortcuts_label.setStyleSheet("font-size: 9.5pt;")
        layout.addWidget(self._shortcuts_label)
        layout.addStretch()
        return page

    def _update_shortcuts_help(self, *_args):
        """Mantiene el texto de ayuda de la pagina 'Atajos' mostrando la
        combinacion realmente seleccionada en self._hotkey_combo, en vez
        de un 'Ctrl+Alt+Espacio' fijo que quedaba mostrando el default
        aunque el usuario hubiera elegido otra cosa."""
        self._shortcuts_label.setText(_shortcuts_html(self._hotkey_combo.currentText()))

    # ---------- vista previa en vivo ----------

    def _rebuild_preview(self, *_args):
        while self._preview_holder.count():
            item = self._preview_holder.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        self._preview_card = LauncherCard(
            dict(_PREVIEW_ENTRY),
            base_height=self._card_height_slider.value(),
            expand_px=self._expand_slider.value(),
            bg_alpha=self._alpha_slider.value(),
            duration_ms=self._duration_slider.value(),
            easing=_value_of(self._easing_combo, _EASING_OPTIONS),
            slide_px=self._slide_px_slider.value(),
            slide_direction=_value_of(self._slide_combo, _SLIDE_OPTIONS),
            slide_mode=_value_of(self._slide_mode_combo, _SLIDE_MODE_OPTIONS),
            arrow_side_preference=_value_of(self._arrow_side_combo, _ARROW_SIDE_OPTIONS),
            speed_multiplier=self._speed_slider.value() / 100,
        )
        self._preview_holder.addWidget(self._preview_card)
        self._preview_state = False

    def _toggle_preview(self):
        if self._preview_card is None:
            return
        self._preview_state = not self._preview_state
        try:
            self._preview_card.trigger_preview(self._preview_state)
        except RuntimeError:
            pass  # se estaba reconstruyendo justo en este instante

    # ---------- categorias ----------

    def _enabled_auto_rules(self) -> list:
        """Ids de las reglas automaticas tildadas AHORA en el panel (aunque
        todavia no se haya guardado)."""
        return [rule_id for rule_id, check in self._auto_rule_checks.items() if check.isChecked()]

    def _selected_category_id(self):
        item = self._category_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _reload_category_list(self, select_group_id=None):
        """select_group_id: categoria a dejar seleccionada tras recargar
        (por defecto, la que ya estaba seleccionada, si sigue existiendo)."""
        if select_group_id is None:
            select_group_id = self._selected_category_id()
        self._category_list.clear()
        select_row = 0
        for row, cat in enumerate(self.launcher_manager.categories()):
            count = cat["count"]
            text = f"{cat['title']}   -   {count} app" + ("" if count == 1 else "s")
            if cat["is_default"]:
                text += "   (por defecto)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, cat["group_id"])
            self._category_list.addItem(item)
            if cat["group_id"] == select_group_id:
                select_row = row
        self._category_list.setCurrentRow(select_row)
        self._update_category_buttons()

    def _update_category_buttons(self, *_args):
        cats = self.launcher_manager.categories()
        selected = self._selected_category_id()
        index = next((i for i, c in enumerate(cats) if c["group_id"] == selected), None)
        has = index is not None
        self._cat_rename_btn.setEnabled(has)
        self._cat_delete_btn.setEnabled(has and not cats[index]["is_default"])
        self._cat_up_btn.setEnabled(has and index > 0)
        self._cat_down_btn.setEnabled(has and index < len(cats) - 1)

    def _on_category_new(self):
        name = ask_category_name(
            self, self.launcher_manager, "Nueva categoría", "Nombre de la categoría:"
        )
        if name is None:
            return
        try:
            group_id = self.launcher_manager.create_category(name)
        except ValueError as e:  # otro hilo/dialogo pudo crear el mismo nombre entre medio
            QMessageBox.warning(self, "Nueva categoría", str(e))
            return
        self._reload_category_list(select_group_id=group_id)

    def _on_category_rename(self):
        group_id = self._selected_category_id()
        cat = next((c for c in self.launcher_manager.categories() if c["group_id"] == group_id), None)
        if cat is None:
            return
        name = ask_category_name(
            self, self.launcher_manager, "Renombrar categoría", "Nuevo nombre:",
            initial=cat["title"], exclude_group_id=group_id,
        )
        if name is None:
            return
        try:
            self.launcher_manager.rename_category(group_id, name)
        except ValueError as e:
            QMessageBox.warning(self, "Renombrar categoría", str(e))
            return
        self._reload_category_list(select_group_id=group_id)

    def _on_category_delete(self):
        group_id = self._selected_category_id()
        cat = next((c for c in self.launcher_manager.categories() if c["group_id"] == group_id), None)
        if cat is None or cat["is_default"]:
            return
        if cat["count"] > 0:
            answer = QMessageBox.question(
                self, "Eliminar categoría",
                f"Se eliminará la categoría '{cat['title']}'. Sus {cat['count']} app(s) "
                "no se borran: pasan a la categoría por defecto.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.launcher_manager.delete_category(group_id)
        self._reload_category_list()

    def _on_category_move(self, delta: int):
        group_id = self._selected_category_id()
        if group_id is not None and self.launcher_manager.move_category(group_id, delta):
            self._reload_category_list(select_group_id=group_id)

    # ---------- deshacer apps quitadas ----------

    def _reload_hidden_list(self):
        self._hidden_list.clear()
        hidden = self.launcher_manager.hidden_entries()
        if not hidden:
            placeholder = QListWidgetItem("(no hay apps quitadas)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._hidden_list.addItem(placeholder)
            return
        for entry in hidden:
            item = QListWidgetItem(entry.get("name", entry.get("id", "?")))
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self._hidden_list.addItem(item)

    def _on_restore_selected(self):
        selected = self._hidden_list.selectedItems()
        for item in selected:
            entry_id = item.data(Qt.ItemDataRole.UserRole)
            if entry_id:
                self.launcher_manager.unhide_entry(entry_id)
        self._reload_hidden_list()

    # ---------- deteccion: buscar de nuevo ahora ----------

    def _on_rescan_clicked(self):
        """Vuelve a escanear de inmediato, con las fuentes que esten
        tildadas en este mismo momento (aunque todavia no se haya
        apretado Guardar) -- para que "probar" no dependa de guardar
        primero.

        Antes esto llamaba a launcher_manager.refresh() DIRECTO en el
        hilo de UI, bloqueando TODO el dialogo (cursor de espera +
        QApplication.processEvents() a mano para que al menos se
        alcanzara a pintar) mientras duraba -- un escaneo en frio, sin
        nada todavia en cache/extracted_icons/, puede tardar varios
        segundos con un Menu Inicio grande, y en ese rato el dialogo
        completo de Configuracion quedaba congelado (ni siquiera se
        podia cambiar de pagina a mirar otra cosa mientras tanto). Ahora
        reusa el mismo mecanismo de QThread en background que ya usa el
        escaneo automatico al iniciar (ver start_scan en
        core/scan_worker.py y MainWindow.start_background_scan) -- el
        resto del dialogo queda usable mientras corre.

        self._rescan_running sigue cortando el reintento (doble click,
        o apretar el boton nuevamente ya con un escaneo en curso); ahora
        ademas Guardar/Cancelar se deshabilitan mientras tanto (ver
        closeEvent/reject mas abajo) para que el dialogo no se cierre
        con el QThread todavia corriendo contra un self ya destruido."""
        if getattr(self, "_rescan_running", False):
            return
        self._rescan_running = True
        self._rescan_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._rescan_status.setText("Buscando...")
        self._rescan_thread, self._rescan_worker = start_scan(
            self.launcher_manager,
            on_finished=self._on_rescan_finished,
            on_failed=self._on_rescan_failed,
            scan_steam=self._scan_steam_check.isChecked(),
            scan_shortcuts=self._scan_shortcuts_check.isChecked(),
            scan_uwp=self._scan_uwp_check.isChecked(),
            auto_rules=self._enabled_auto_rules(),
        )

    def _on_rescan_finished(self):
        self._rescan_status.setText("Lista actualizada.")
        self._rescan_done()

    def _on_rescan_failed(self, message: str):
        self._rescan_status.setText(f"No se pudo completar el escaneo: {message}")
        self._rescan_done()

    def _rescan_done(self):
        self._rescan_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._rescan_running = False
        self._reload_hidden_list()
        self._reload_category_list()

    def closeEvent(self, event):
        """Ignora el cierre (X de la ventana / Alt+F4) mientras haya un
        rescan en background corriendo -- ver _on_rescan_clicked. Cerrar
        el dialogo a mitad de un escaneo dejaria el QThread corriendo
        contra una SettingsWindow ya destruida (crash o warning de Qt al
        terminar e intentar llamar a _on_rescan_finished/_failed)."""
        if getattr(self, "_rescan_running", False):
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        """Mismo motivo que closeEvent: Cancelar y Escape pasan por
        aca."""
        if getattr(self, "_rescan_running", False):
            return
        super().reject()

    def done(self, result):
        """Todo cierre del dialogo (Guardar, Cancelar, Escape) pasa por
        aca: se detiene el temporizador de la vista previa."""
        timer = getattr(self, "_preview_timer", None)
        if timer is not None:
            timer.stop()
        super().done(result)

    # ---------- guardar ----------

    def _on_save(self):
        self._settings.setdefault("window", {})["background_alpha"] = self._alpha_slider.value()
        self._settings["window"]["width"] = self._width_slider.value()
        self._settings["window"]["always_on_top"] = self._always_on_top_check.isChecked()
        self._settings["window"]["show_tooltips"] = self._tooltips_check.isChecked()
        self._settings["window"]["compact_card_height"] = self._card_height_slider.value()
        self._settings["window"]["sort_mode"] = _value_of(self._sort_combo, _SORT_OPTIONS)
        self._settings["hotkey_toggle"] = _value_of(self._hotkey_combo, _HOTKEY_OPTIONS)

        detection = self._settings.setdefault("detection", {})
        detection["auto_scan_on_launch"] = self._auto_scan_check.isChecked()
        detection["scan_steam"] = self._scan_steam_check.isChecked()
        detection["scan_shortcuts"] = self._scan_shortcuts_check.isChecked()
        detection["scan_uwp"] = self._scan_uwp_check.isChecked()

        anim = self._settings.setdefault("animation", {})
        anim["duration_ms"] = self._duration_slider.value()
        anim["hover_expand_px"] = self._expand_slider.value()
        anim["easing"] = _value_of(self._easing_combo, _EASING_OPTIONS)
        anim["speed_multiplier"] = self._speed_slider.value() / 100
        anim["hover_slide_direction"] = _value_of(self._slide_combo, _SLIDE_OPTIONS)
        anim["hover_slide_px"] = self._slide_px_slider.value()
        anim["hover_slide_mode"] = _value_of(self._slide_mode_combo, _SLIDE_MODE_OPTIONS)
        anim["arrow_side_preference"] = _value_of(self._arrow_side_combo, _ARROW_SIDE_OPTIONS)
        anim["expand_overlay_height_px"] = self._expand_height_slider.value()

        self._settings.setdefault("buttons", {})["special_buttons_placement"] = _value_of(
            self._placement_combo, _PLACEMENT_OPTIONS
        )

        self._settings["auto_categories"] = {
            rule_id: check.isChecked() for rule_id, check in self._auto_rule_checks.items()
        }

        save_settings(self._settings)
        # Que activar una regla surta efecto ya, sin esperar al proximo
        # escaneo (no re-escanea: solo reparte lo que ya esta cargado).
        self.launcher_manager.apply_auto_categories(self._enabled_auto_rules())
        self.accept()
