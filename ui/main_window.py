"""
main_window.py
-----------------
Ventana principal: panel sin bordes y translucido con el buscador, la
lista de apps y los botones "Agregar app" / "Configuración". Tambien es
dueña del icono de la bandeja, del atajo global y de los avisos (toast).

Tres formas de mostrar la lista (self._list_mode)
---------------------------------------------------
* "loop": 3 copias reales de la lista con scroll en bucle. Al llegar a
  un extremo se salta una "vuelta" (+-alto de una copia) hacia la copia
  del medio; como son identicas, el salto no se ve. Solo si una copia es
  mas alta que el area visible: si no, las copias se verian repetidas.
* "single": una copia, scroll normal. Listas que entran en pantalla y
  resultados de busqueda chicos.
* "virtual": pool reciclado de ui/virtual_card_list.py, scroll normal.
  A partir de _VIRTUALIZE_THRESHOLD apps (o resultados de busqueda).
  Mientras la configuracion visual no cambie, el pool se REUTILIZA entre
  reconstrucciones: solo se le pasan los datos nuevos.
* "empty": un mensaje (buscando, sin resultados, sin apps).

Zonas invisibles pero que reciben el mouse
--------------------------------------------
En una ventana con WA_TranslucentBackground, Windows deja pasar los
clics por los pixeles con alpha 0. El contenido se pinta con alpha 1
(QColor via QPalette, no QSS) para recibir rueda y arrastre sin verse.

Hover y contenido que se mueve solo
-------------------------------------
Qt solo entrega enter/leave cuando el mouse se mueve. Cuando el
contenido cambia bajo un cursor quieto (scroll, salto del bucle,
reconstruccion) el hover queda desincronizado; _resync_all_hover_states
lo corrige contra la posicion real del cursor.

Regla para los handlers de acciones
-------------------------------------
Nunca reconstruir la lista ni abrir un dialogo dentro de la senal de una
tarjeta o de un boton: se difiere con QTimer.singleShot(0, ...). La
reconstruccion destruye widgets, y el que emitio la senal todavia esta
mas arriba en la pila.
"""

import math
import os
import time

from PySide6.QtCore import QAbstractAnimation, QEvent, QPropertyAnimation, QRect, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core import auto_categories, search
from core.config_manager import load_settings, save_settings
from core.debug_log import log as debug_log
from core.paths import DATA_DIR
from core.scan_worker import start_icon_resolve, start_scan
from ui import toast
from ui.add_app_dialog import AddAppDialog
from ui.app_icon import build_app_icon
from ui.category_dialogs import ask_category_name
from ui.expand_overlay import ExpandOverlay
from ui.global_hotkey import GlobalHotkey
from ui.launcher_card import LauncherCard
from ui.settings_window import SettingsWindow
from ui.special_button import SpecialButton
from ui.text_utils import elide_label_text
from ui.virtual_card_list import VirtualCardList

_NUM_COPIES = 3
_MIDDLE_COPY_INDEX = 1

# A partir de esta cantidad de apps a mostrar (sumando categorias, o
# resultados de busqueda) se usa el pool reciclado en vez de una tarjeta
# real por app. No aplica con los botones "dentro de la lista".
_VIRTUALIZE_THRESHOLD = 60
_VIRTUALIZE_OVERSCAN = 6

# Separacion vertical entre filas, igual en los tres modos de lista.
_ROW_SPACING = 10

# Pulso de "respiracion" de los botones especiales: un solo reloj para
# todos. ~22 repintados por segundo alcanzan para una curva tan suave.
_PULSE_TICK_MS = 45
_PULSE_TICK_STEP = 0.075
# Cada cuantos ticks corre la red de seguridad contra hover pegado.
_HOVER_SAFETY_EVERY_N_TICKS = 6

_SEARCH_DEBOUNCE_MS = 110
# Un doble clic no debe abrir la app dos veces.
_DOUBLE_LAUNCH_GUARD_S = 1.0

_ADD_APP_ACCENT = QColor(80, 220, 170)     # verde-cyan
_SETTINGS_ACCENT = QColor(150, 140, 255)   # violeta

_SEARCH_GROUP_ID = "__search__"
_HEADER_STYLE = "color: rgba(255,255,255,150); font-size: 10pt; font-weight: bold;"
_SEARCH_PLACEHOLDER = "Buscar apps…  (Enter abre la primera)"
_SCANNING_PLACEHOLDER = "Actualizando la lista…"
_IMAGE_FILTER = "Imágenes (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"

_SOURCE_NAMES = {"steam": "Steam", "shortcuts": "los accesos directos", "uwp": "Microsoft Store"}


def _make_invisible_but_hit_testable(widget: QWidget):
    """Pinta el widget con alpha=1 real para que reciba mouse y rueda
    sin verse (ver el docstring del modulo)."""
    widget.setAutoFillBackground(True)
    palette = widget.palette()
    palette.setColor(widget.backgroundRole(), QColor(0, 0, 0, 1))
    widget.setPalette(palette)


def _short(name, limit: int = 34) -> str:
    """Nombre recortado para que un aviso entre en el ancho de la ventana."""
    name = str(name or "").strip() or "la aplicación"
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


class MainWindow(QWidget):
    # Cuanto espera el cierre a los hilos de fondo antes de rendirse.
    # Pasado esto main.py termina el proceso igual: todo lo del usuario
    # ya esta en disco.
    _SHUTDOWN_WAIT_MS = 1500

    def __init__(self, launcher_manager, settings: dict):
        super().__init__()
        self.launcher_manager = launcher_manager
        self.settings = settings

        # --- estado de la lista ---
        self._list_mode = "empty"
        self._copies = []
        self._copy_height = 0
        self._virtual_list = None
        self._virtual_rows = (1, 1)       # (alto de fila de app, alto de fila de titulo)
        self._view_key = None             # config visual con que se armo el pool virtual
        self._infinite_scroll_connected = False
        self._virtual_scroll_connected = False
        self._live_cards = []             # LauncherCard vivas (ver _wire_card)
        self._special_buttons = []        # todos los botones especiales vivos
        self._footer = None
        self._footer_key = None
        self._footer_buttons = []

        # --- busqueda y navegacion con teclado ---
        self._search_query = ""
        self._layout_query = None         # busqueda con que se armo la lista actual
        self._nav_entries = []            # entradas en el orden en que se ven
        self._selected_id = None          # la que abriria Enter

        # --- acciones ---
        self._last_launch = (None, 0.0)   # (id, momento) del ultimo lanzamiento
        self._dialog_open = False
        self._drag_pos = None
        self._press_pos = None
        self._drag_moved = False
        self._active_expand_card = None

        # --- trabajo en segundo plano ---
        self._scanning = False
        self._scan_thread = None
        self._scan_worker = None
        # Una entrada por cada icono de app manual que se esta extrayendo.
        # Lista (y no un unico par) para no perder la referencia a un hilo
        # todavia vivo si se agregan dos apps seguidas.
        self._icon_resolve_jobs = []
        self._shutting_down = False

        self._applied_on_top = None
        self._apply_window_flags()

        width = settings.get("window", {}).get("width", 380)
        self.setFixedWidth(width)
        screen = QApplication.primaryScreen()
        height = screen.availableGeometry().height() if screen else 800
        self.resize(width, height)
        self._restore_position()

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(20, 30, 20, 15)
        self._outer.setSpacing(10)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(_SEARCH_PLACEHOLDER)
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setStyleSheet(
            "QLineEdit {"
            "  background-color: rgba(18,19,28,205);"
            "  color: white;"
            "  border: 1px solid rgba(255,255,255,45);"
            "  border-radius: 9px;"
            "  padding: 7px 11px;"
            "  font-size: 10pt;"
            "  selection-background-color: rgba(150,140,255,170);"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid rgba(150,140,255,210);"
            "}"
        )
        self._search_box.textChanged.connect(self._on_search_changed)
        self._search_box.returnPressed.connect(self._launch_selected)
        self._search_box.installEventFilter(self)  # flechas: ver eventFilter

        # Escribir rapido no debe reconstruir la lista en cada tecla.
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._refresh_layout)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _make_invisible_but_hit_testable(self._scroll_area.viewport())
        self._scroll_area.verticalScrollBar().setSingleStep(28)

        # El scroll dispara muchos valueChanged por segundo; la
        # resincronizacion de hover se agrupa con un temporizador corto.
        self._hover_resync_timer = QTimer(self)
        self._hover_resync_timer.setSingleShot(True)
        self._hover_resync_timer.setInterval(40)
        self._hover_resync_timer.timeout.connect(self._resync_all_hover_states)
        self._scroll_area.verticalScrollBar().valueChanged.connect(
            lambda _v: self._hover_resync_timer.start()
        )

        self._outer.addWidget(self._search_box)
        self._outer.addWidget(self._scroll_area, 1)

        self._expand_overlay = ExpandOverlay(self)
        self._expand_overlay.mouse_left.connect(self._on_collapse_requested)
        self._expand_overlay.launch_requested.connect(self._on_card_clicked)

        self._toast = toast.Toast(self)

        self._refresh_layout()

        # Escape: primero limpia la busqueda; sin busqueda, oculta.
        self._close_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._close_shortcut.activated.connect(self._on_escape)

        # Con los botones especiales ocultos, este atajo es la forma de
        # abrir Configuracion (ademas del menu de la bandeja).
        self._settings_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._settings_shortcut.activated.connect(self._on_settings_clicked)

        self._build_tray_icon()

        self._pulse_phase = 0.0
        self._pulse_tick_count = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_timer.start(_PULSE_TICK_MS)

        # Atajo global (solo Windows, ver ui/global_hotkey.py).
        self._hotkey_str = self.settings.get("hotkey_toggle", "ctrl+alt+space")
        self._global_hotkey = self._register_hotkey(self._hotkey_str)

        # Fade-in al mostrar y fade-out al ocultar. Una sola conexion a
        # 'finished': el hide() real ocurre solo si la animacion iba a 0.
        self._fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_animation.setDuration(220)
        self._fade_animation.finished.connect(self._on_fade_finished)

    # =================================================================
    # Ventana: mostrar, ocultar, bandeja, cierre
    # =================================================================

    def _pulse_tick(self):
        self._pulse_phase = (self._pulse_phase + _PULSE_TICK_STEP) % (2 * math.pi)
        for btn in self._special_buttons:
            try:
                btn.set_glow_phase(self._pulse_phase)
            except RuntimeError:
                pass  # widget ya destruido por una reconstruccion en curso

        self._pulse_tick_count += 1
        if self._pulse_tick_count % _HOVER_SAFETY_EVERY_N_TICKS == 0:
            self._check_stale_hover()
            # Un hijo que acepta el mouseRelease (mini-boton) impide que
            # llegue aca: el estado de arrastre no debe quedar pegado.
            if self._drag_moved and not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._drag_moved = False
                self._drag_pos = None

    def showEvent(self, event):
        if hasattr(self, "_pulse_timer"):
            self._pulse_timer.start()
        if hasattr(self, "_fade_animation"):
            self._fade_animation.stop()  # stop() no dispara finished
            self._fade_animation.setStartValue(0.0)
            self._fade_animation.setEndValue(1.0)
            self._fade_animation.start()
        super().showEvent(event)
        # Listo para escribir: el flujo es atajo -> texto -> Enter.
        QTimer.singleShot(0, self._focus_search)

    def hideEvent(self, event):
        if hasattr(self, "_pulse_timer"):
            self._pulse_timer.stop()
        if hasattr(self, "_toast"):
            self._toast.hide()
        super().hideEvent(event)

    def _focus_search(self):
        if self._shutting_down or not self.isVisible():
            return
        self._search_box.setFocus()
        self._search_box.selectAll()  # escribir reemplaza la busqueda anterior

    def _on_fade_finished(self):
        if self._fade_animation.endValue() == 0.0:
            self.hide()

    def _hide_animated(self):
        if not self.isVisible():
            return
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self.windowOpacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

    def closeEvent(self, event):
        # Cerrar la ventana solo la oculta; el programa sigue en la
        # bandeja. Salir de verdad es "Cerrar" en el menu de la bandeja.
        event.ignore()
        self._hide_animated()
        if hasattr(self, "_toggle_action"):
            self._toggle_action.setText("Mostrar")

    def _on_escape(self):
        if self._search_box.text():
            self._search_box.clear()
        else:
            self.close()

    def _build_tray_icon(self):
        self._tray_icon = QSystemTrayIcon(build_app_icon(), self)
        self._tray_icon.setToolTip("SPECTRUM Launcher")

        self._tray_menu = QMenu()

        self._toggle_action = self._tray_menu.addAction("Ocultar")
        self._toggle_action.triggered.connect(self._toggle_visibility)

        settings_action = self._tray_menu.addAction("Configuración")
        settings_action.triggered.connect(self._on_settings_clicked)

        data_action = self._tray_menu.addAction("Abrir carpeta de datos")
        data_action.triggered.connect(self._open_data_folder)

        self._tray_menu.addSeparator()

        quit_action = self._tray_menu.addAction("Cerrar")
        quit_action.triggered.connect(self._on_quit)

        # Clic derecho: menu nativo. Clic izquierdo: el mismo menu, a mano.
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_menu.popup(QCursor.pos())

    def _toggle_visibility(self):
        # Durante el fade-out la ventana sigue "visible": se trata como
        # oculta para que el atajo la vuelva a traer.
        hiding = (
            self._fade_animation.state() == QAbstractAnimation.State.Running
            and self._fade_animation.endValue() == 0.0
        )
        if self.isVisible() and not hiding:
            self._hide_animated()
            self._toggle_action.setText("Mostrar")
        else:
            self.show_and_raise()

    def show_and_raise(self):
        """Muestra la ventana y la trae al frente. Lo usan el atajo
        global, la bandeja y el guard de instancia unica (cuando se
        vuelve a ejecutar el programa estando ya abierto)."""
        if self.isVisible():
            # Puede estar a mitad de un fade-out: se revierte.
            self._fade_animation.stop()
            self._fade_animation.setStartValue(self.windowOpacity())
            self._fade_animation.setEndValue(1.0)
            self._fade_animation.start()
        self.show()
        self.raise_()
        self.activateWindow()
        self._toggle_action.setText("Ocultar")
        QTimer.singleShot(0, self._focus_search)

    def _open_data_folder(self):
        """Abre la carpeta de datos del usuario (ver core/paths.py)."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR))

    def _on_quit(self):
        self.shutdown()
        QApplication.instance().quit()

    def shutdown(self):
        """Cierre ordenado e idempotente (Cerrar, aboutToQuit, Ctrl+C)."""
        if self._shutting_down:
            return
        self._shutting_down = True
        debug_log("shutdown(): cerrando")

        # Que desaparezca todo de inmediato; lo que sigue puede tardar.
        if hasattr(self, "_tray_icon"):
            self._tray_icon.hide()
        self.hide()
        if hasattr(self, "_expand_overlay"):
            self._expand_overlay.hide()
        if hasattr(self, "_global_hotkey"):
            self._global_hotkey.unregister()

        for name in ("_pulse_timer", "_search_debounce", "_hover_resync_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()

        self._stop_background_threads(self._SHUTDOWN_WAIT_MS)

    def _stop_background_threads(self, timeout_ms: int):
        """Pide que terminen los QThread de escaneo e iconos y espera, en
        total, hasta timeout_ms. Los que sigan corriendo se dejan."""
        threads = [self._scan_thread] + [t for (t, _w) in self._icon_resolve_jobs]
        deadline = time.monotonic() + timeout_ms / 1000.0
        for thread in threads:
            if thread is None:
                continue
            try:
                if not thread.isRunning():
                    continue
                thread.quit()
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if not thread.wait(remaining):
                    debug_log("shutdown(): un hilo de fondo no termino a tiempo; se cierra igual")
            except RuntimeError:
                pass  # el QThread ya fue destruido por su deleteLater()

    def _apply_window_flags(self):
        """Tool = sin boton en la barra de tareas ni en Alt+Tab. Cambiar
        los flags recrea la ventana nativa, asi que solo se hace si
        'siempre visible' cambio de verdad."""
        on_top = bool(self.settings.get("window", {}).get("always_on_top", True))
        if on_top == self._applied_on_top:
            return
        self._applied_on_top = on_top

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint

        was_visible = self.isVisible()
        geo = self.geometry() if was_visible else None
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if was_visible:
            self.setGeometry(geo)
            self.show()

    def _restore_position(self):
        """Vuelve a la ultima posicion guardada, si sigue cayendo dentro
        de alguna pantalla (pudo desconectarse un monitor)."""
        win_cfg = self.settings.get("window", {})
        x, y = win_cfg.get("x"), win_cfg.get("y")
        if not (isinstance(x, int) and isinstance(y, int)) or isinstance(x, bool):
            return
        top_strip = QRect(x, y, self.width(), 120)
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(top_strip):
                self.move(x, y)
                return

    def _save_position(self):
        pos = self.pos()
        win_cfg = self.settings.setdefault("window", {})
        if win_cfg.get("x") == pos.x() and win_cfg.get("y") == pos.y():
            return
        win_cfg["x"], win_cfg["y"] = pos.x(), pos.y()
        try:
            save_settings(self.settings)
        except OSError as e:
            debug_log(f"No se pudo guardar la posicion de la ventana: {e}")

    def _register_hotkey(self, hotkey_str: str):
        hotkey = GlobalHotkey(
            QApplication.instance(), hotkey_str, on_triggered=self._toggle_visibility
        )
        if getattr(hotkey, "failed", False):
            self._notify(
                f"No se pudo registrar el atajo {hotkey_str}. Puede que lo use otro programa.",
                toast.ERROR, tray=True,
            )
        return hotkey

    # =================================================================
    # Avisos
    # =================================================================

    def toast_area(self) -> QRect:
        """Zona sobre la que se centra el aviso (ver ui/toast.py)."""
        return self._scroll_area.geometry()

    def _notify(self, text: str, kind: str = toast.INFO, action_text: str = "",
                on_action=None, tray: bool = False):
        """Aviso dentro de la ventana. Con tray=True, si la ventana esta
        oculta se usa un globo de la bandeja en su lugar (para errores
        que el usuario tiene que ver igual)."""
        if self._shutting_down:
            return
        if self.isVisible() and hasattr(self, "_toast"):
            self._toast.show_message(text, kind, action_text, on_action)
        elif tray and hasattr(self, "_tray_icon"):
            icon = (QSystemTrayIcon.MessageIcon.Warning if kind == toast.ERROR
                    else QSystemTrayIcon.MessageIcon.Information)
            self._tray_icon.showMessage("SPECTRUM Launcher", text, icon, 4000)

    def _entry_name(self, entry_id: str) -> str:
        entry = self.launcher_manager.get_entry(entry_id)
        return _short(entry.get("name") if entry else "")

    # =================================================================
    # Escaneo en segundo plano
    # =================================================================

    def _set_scanning(self, scanning: bool):
        self._scanning = scanning
        self._search_box.setPlaceholderText(
            _SCANNING_PLACEHOLDER if scanning else _SEARCH_PLACEHOLDER
        )

    def start_background_scan(self):
        """Lanza la deteccion (segun settings["detection"]) en otro hilo.
        Lo que ya habia en cache se sigue viendo mientras tanto."""
        detection_cfg = self.settings.get("detection", {})
        if not detection_cfg.get("auto_scan_on_launch", True):
            return

        self._set_scanning(True)
        if self._list_mode == "empty":
            self._refresh_layout()  # cambia el mensaje a "Buscando..."
        self._scan_thread, self._scan_worker = start_scan(
            self.launcher_manager,
            on_finished=self._on_scan_finished,
            on_failed=self._on_scan_failed,
            scan_steam=detection_cfg.get("scan_steam", True),
            scan_shortcuts=detection_cfg.get("scan_shortcuts", True),
            scan_uwp=detection_cfg.get("scan_uwp", True),
            auto_rules=auto_categories.enabled_from_settings(self.settings),
        )

    def _on_scan_finished(self):
        was_empty = self._list_mode == "empty"
        self._set_scanning(False)
        summary = getattr(self.launcher_manager, "last_refresh", None) or {}
        # Si el escaneo no encontro cambios, la lista no se toca: se
        # evita reconstruirla bajo el cursor en cada arranque.
        if summary.get("changed") or was_empty:
            self._refresh_layout()

        failed = [_SOURCE_NAMES.get(s, s) for s in summary.get("failed", [])]
        added, removed = summary.get("added", 0), summary.get("removed", 0)
        if failed:
            self._notify(
                f"No se pudo leer {' ni '.join(failed)}. Se conserva lo que ya había.",
                toast.ERROR,
            )
        elif was_empty and added:
            self._notify(f"{added} apps encontradas", toast.SUCCESS)
        elif added or removed:
            parts = []
            if added:
                parts.append(f"{added} nueva{'s' if added != 1 else ''}")
            if removed:
                parts.append(f"{removed} quitada{'s' if removed != 1 else ''}")
            self._notify("Lista actualizada: " + ", ".join(parts), toast.SUCCESS)

    def _on_scan_failed(self, message: str):
        self._set_scanning(False)
        debug_log(f"Escaneo en background fallo: {message}")
        if self._list_mode == "empty":
            self._refresh_layout()
        self._notify("No se pudo actualizar la lista de apps.", toast.ERROR)

    # =================================================================
    # Construccion de la lista
    # =================================================================

    def _current_cfg(self) -> dict:
        win_cfg = self.settings.get("window", {})
        anim_cfg = self.settings.get("animation", {})
        return {
            "card_h": win_cfg.get("compact_card_height", 50),
            "bg_alpha": win_cfg.get("background_alpha", 220),
            "expand_px": anim_cfg.get("hover_expand_px", 34),
            "duration_ms": anim_cfg.get("duration_ms", 220),
            "easing": anim_cfg.get("easing", "OutCubic"),
            "slide_px": anim_cfg.get("hover_slide_px", 0),
            "slide_direction": anim_cfg.get("hover_slide_direction", "none"),
            "slide_mode": anim_cfg.get("hover_slide_mode", "content_only"),
            "show_tooltip": win_cfg.get("show_tooltips", False),
            "arrow_side_preference": anim_cfg.get("arrow_side_preference", "right"),
            "expand_overlay_height_px": anim_cfg.get("expand_overlay_height_px", 220),
            "speed_multiplier": anim_cfg.get("speed_multiplier", 1.0),
        }

    def _new_card(self, entry: dict, cfg: dict) -> LauncherCard:
        card = LauncherCard(
            entry,
            base_height=cfg["card_h"],
            expand_px=cfg["expand_px"],
            bg_alpha=cfg["bg_alpha"],
            duration_ms=cfg["duration_ms"],
            easing=cfg["easing"],
            slide_px=cfg["slide_px"],
            slide_direction=cfg["slide_direction"],
            slide_mode=cfg["slide_mode"],
            show_tooltip=cfg["show_tooltip"],
            arrow_side_preference=cfg["arrow_side_preference"],
            speed_multiplier=cfg["speed_multiplier"],
        )
        self._wire_card(card)
        return card

    def _wire_card(self, card):
        """Unico lugar donde una tarjeta se conecta a esta ventana, para
        los dos caminos que crean tarjetas (copias reales y pool)."""
        card.clicked.connect(self._on_card_clicked)
        card.remove_requested.connect(self._on_remove_requested)
        card.background_image_changed.connect(self._on_background_image_changed)
        card.background_pick_requested.connect(self._on_background_pick_requested)
        card.favorite_toggled.connect(self._on_favorite_toggled)
        card.expand_requested.connect(self._on_expand_requested)
        card.collapse_requested.connect(self._on_collapse_requested)
        card.category_move_requested.connect(self._on_category_move_requested)
        card.new_category_requested.connect(self._on_new_category_requested)
        card.category_provider = self._category_choices
        self._live_cards.append(card)

    def _make_special_buttons(self, card_h: int) -> list:
        add_btn = SpecialButton("Agregar app", "+", _ADD_APP_ACCENT, height=card_h)
        add_btn.clicked.connect(self._on_add_app_clicked)
        settings_btn = SpecialButton("Configuración", "⚙", _SETTINGS_ACCENT, height=card_h)
        settings_btn.clicked.connect(self._on_settings_clicked)
        return [add_btn, settings_btn]

    def _ensure_footer(self, placement: str, card_h: int):
        """Los botones de abajo ("Fuera de la lista") son persistentes:
        solo se rehacen si cambia su ubicacion o su alto."""
        key = (placement == "outside", card_h)
        if key == self._footer_key:
            return
        self._footer_key = key
        if self._footer is not None:
            self._outer.removeWidget(self._footer)
            self._footer.setParent(None)
            self._footer.deleteLater()
            self._footer = None
        self._footer_buttons = []
        if placement != "outside":
            return
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 12, 0, 0)
        footer_layout.setSpacing(8)
        self._footer_buttons = self._make_special_buttons(card_h)
        for button in self._footer_buttons:
            footer_layout.addWidget(button)
        self._outer.addWidget(footer)
        self._footer = footer

    def _build_group_stack(self, groups, cfg, include_buttons: bool) -> QWidget:
        """Una copia real de la lista: titulo + tarjetas por categoria."""
        stack = QWidget()
        _make_invisible_but_hit_testable(stack)

        layout = QVBoxLayout(stack)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_ROW_SPACING)

        for group in groups:
            launchers = group.get("launchers", [])
            if not launchers:
                continue
            title = QLabel()
            title.setStyleSheet(_HEADER_STYLE)
            # Ancho disponible = ventana menos los margenes laterales.
            elide_label_text(
                title, group.get("title", group.get("group_id", "")), self.width() - 40
            )
            layout.addWidget(title)
            for entry in launchers:
                layout.addWidget(self._new_card(entry, cfg))

        if include_buttons:
            for button in self._make_special_buttons(cfg["card_h"]):
                layout.addWidget(button)
                self._special_buttons.append(button)

        return stack

    def _should_virtualize(self, groups: list, placement: str, searching: bool = False) -> bool:
        """Con los botones "dentro de la lista" no se virtualiza: habria
        que virtualizar tambien esas filas."""
        if placement == "inside":
            return False
        return sum(len(g.get("launchers", [])) for g in groups) >= _VIRTUALIZE_THRESHOLD

    def _build_virtual_container(self, groups: list, cfg: dict) -> QWidget:
        container = QWidget()
        _make_invisible_but_hit_testable(container)

        def header_factory():
            label = QLabel()
            label.setStyleSheet(_HEADER_STYLE)
            label.setFixedHeight(
                max(label.sizeHint().height(), label.fontMetrics().height() + 4)
            )
            return label

        placeholder = {"id": "__pool__", "name": "", "icon": "auto", "target": ""}

        def card_factory():
            return self._new_card(placeholder, cfg)

        probe = header_factory()
        header_row_height = probe.height() + _ROW_SPACING
        probe.deleteLater()
        card_row_height = cfg["card_h"] + cfg["expand_px"] + _ROW_SPACING
        self._virtual_rows = (card_row_height, header_row_height)

        self._virtual_list = VirtualCardList(
            container, card_factory, header_factory, overscan=_VIRTUALIZE_OVERSCAN
        )
        self._virtual_list.set_groups(
            groups, card_row_height, header_row_height, self._viewport_height(), scroll_value=0
        )
        return container

    def _viewport_height(self) -> int:
        """Alto del area visible de la lista. Antes de mostrarse la
        ventana el layout todavia no corrio: se estima."""
        height = self._scroll_area.viewport().height()
        if self.isVisible() and height > 50:
            return height
        footer = self._footer.sizeHint().height() + _ROW_SPACING if self._footer is not None else 0
        return max(200, self.height() - 100 - footer)

    def _groups_to_show(self):
        """(grupos a mostrar, hay_busqueda). Con busqueda, un unico grupo
        con los resultados ordenados por relevancia (ver core/search.py)."""
        sort_mode = self.settings.get("window", {}).get("sort_mode", "favorites_first")
        all_groups = self.launcher_manager.visible_groups(sort_mode)
        if not search.tokenize(self._search_query):
            return [g for g in all_groups if g.get("launchers")], False

        entries = [e for g in all_groups for e in g.get("launchers", [])]
        results = search.search(entries, self._search_query)
        if not results:
            return [], True
        count = len(results)
        title = "1 resultado" if count == 1 else f"{count} resultados"
        return [{"group_id": _SEARCH_GROUP_ID, "title": title, "launchers": results}], True

    def _empty_message(self, searching: bool) -> str:
        if searching:
            return f"Sin resultados para «{self._search_query.strip()}»."
        if self._scanning:
            return "Buscando tus programas…\n(Steam, accesos directos y Microsoft Store)"
        return "No se detectaron programas.\nUsa «Agregar app» para sumar una."

    def _refresh_layout(self):
        """Pone la lista al dia con los datos, la busqueda y la
        configuracion actuales. Se llama al iniciar, tras cada accion,
        al escribir en el buscador, al terminar un escaneo y al cerrar
        Configuracion. Conserva la posicion de scroll, salvo que la
        busqueda haya cambiado (ahi vuelve arriba)."""
        if self._shutting_down:
            return
        cfg = self._current_cfg()
        placement = self.settings.get("buttons", {}).get("special_buttons_placement", "outside")
        self._ensure_footer(placement, cfg["card_h"])

        groups, searching = self._groups_to_show()
        query = self._search_query.strip() if searching else ""
        query_changed = query != self._layout_query
        self._layout_query = query
        self._update_navigation(groups, searching, query_changed)

        count = sum(len(g["launchers"]) for g in groups)
        if count == 0 and placement != "inside":
            mode = "empty"
        elif self._should_virtualize(groups, placement):
            mode = "virtual"
        else:
            mode = "copies"

        view_key = (placement, self.width(), tuple(sorted(cfg.items())))
        if mode == "virtual" and self._virtual_list is not None and view_key == self._view_key:
            self._update_virtual_content(groups, reset_scroll=query_changed)
        else:
            self._rebuild_content(groups, cfg, placement, mode, searching, query_changed)
            self._view_key = view_key if mode == "virtual" else None

        self._expand_overlay.hide()
        self._active_expand_card = None
        self._apply_selection()
        # Las tarjetas cambiaron bajo un cursor que no se movio.
        QTimer.singleShot(0, self._resync_all_hover_states)

    def _update_virtual_content(self, groups: list, reset_scroll: bool):
        """Camino rapido: el pool ya existe y la configuracion visual no
        cambio; solo se le pasan los datos nuevos."""
        bar = self._scroll_area.verticalScrollBar()
        scroll = 0 if reset_scroll else bar.value()
        card_row_h, header_row_h = self._virtual_rows
        self._virtual_list.set_groups(
            groups, card_row_h, header_row_h, self._viewport_height(), scroll_value=scroll
        )
        if reset_scroll:
            bar.setValue(0)

    def _scroll_within_list(self):
        """Posicion de scroll relativa al inicio de la lista, o None."""
        value = self._scroll_area.verticalScrollBar().value()
        if self._list_mode == "loop" and self._copy_height > 0:
            return (value - self._copy_height) % self._copy_height
        if self._list_mode in ("single", "virtual"):
            return value
        return None

    def _disconnect_scroll_handlers(self):
        bar = self._scroll_area.verticalScrollBar()
        if self._virtual_scroll_connected:
            bar.valueChanged.disconnect(self._on_virtual_scroll)
            self._virtual_scroll_connected = False
        if self._infinite_scroll_connected:
            bar.valueChanged.disconnect(self._handle_infinite_scroll)
            self._infinite_scroll_connected = False

    def _rebuild_content(self, groups, cfg, placement, mode, searching, reset_scroll):
        """Reconstruye el contenido del area de scroll desde cero."""
        restore = None if reset_scroll else self._scroll_within_list()
        bar = self._scroll_area.verticalScrollBar()
        self._disconnect_scroll_handlers()

        # Las tarjetas anteriores se destruyen con el contenido viejo
        # (QScrollArea.setWidget mas abajo).
        self._virtual_list = None
        self._live_cards = []
        self._copies = []
        self._copy_height = 0
        self._special_buttons = list(self._footer_buttons)

        content = QWidget()
        _make_invisible_but_hit_testable(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(_ROW_SPACING)

        if mode == "empty":
            self._list_mode = "empty"
            empty = QLabel(self._empty_message(searching))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: rgba(255,255,255,200); font-size: 10pt;")
            content_layout.addWidget(empty)
        elif mode == "virtual":
            self._list_mode = "virtual"
            container = self._build_virtual_container(groups, cfg)
            content_layout.addWidget(container)
            self._copies.append(container)
            bar.valueChanged.connect(self._on_virtual_scroll)
            self._virtual_scroll_connected = True
        else:
            include_buttons = placement == "inside"
            first = self._build_group_stack(groups, cfg, include_buttons)
            content_layout.addWidget(first)
            self._copies.append(first)
            # El bucle necesita que una copia sola no entre en pantalla.
            if not searching and first.sizeHint().height() > self._viewport_height():
                self._list_mode = "loop"
                for _ in range(_NUM_COPIES - 1):
                    copy_widget = self._build_group_stack(groups, cfg, include_buttons)
                    content_layout.addWidget(copy_widget)
                    self._copies.append(copy_widget)
            else:
                self._list_mode = "single"
                content_layout.addStretch(1)  # la lista arriba, el hueco abajo

        self._scroll_area.setWidget(content)

        # El alto final del contenido se conoce recien cuando el layout
        # corre una vez: el scroll se acomoda en el siguiente ciclo.
        if self._list_mode == "loop":
            QTimer.singleShot(0, lambda: self._init_infinite_scroll(restore))
        elif self._list_mode in ("single", "virtual"):
            QTimer.singleShot(0, lambda: self._restore_scroll(restore or 0))

    def _restore_scroll(self, value: int):
        if self._list_mode not in ("single", "virtual"):
            return
        bar = self._scroll_area.verticalScrollBar()
        bar.setValue(max(0, min(int(value), bar.maximum())))

    def _on_virtual_scroll(self, value: int):
        if self._virtual_list is None:
            return
        self._virtual_list.update_window(value, self._scroll_area.viewport().height())
        self._apply_selection()  # una tarjeta reciclada pudo cambiar de app

    # ---------- scroll en bucle ----------

    def _init_infinite_scroll(self, restore_offset=None):
        if self._list_mode != "loop" or len(self._copies) < _NUM_COPIES:
            return
        spacing = self._scroll_area.widget().layout().spacing()
        self._copy_height = self._copies[0].height() + spacing
        if self._copy_height <= 0:
            return

        bar = self._scroll_area.verticalScrollBar()
        if self._infinite_scroll_connected:
            bar.valueChanged.disconnect(self._handle_infinite_scroll)
            self._infinite_scroll_connected = False

        target = self._copy_height * _MIDDLE_COPY_INDEX
        if restore_offset is not None:
            target = max(0, min(self._copy_height + int(restore_offset), bar.maximum()))
        bar.setValue(target)
        bar.valueChanged.connect(self._handle_infinite_scroll)
        self._infinite_scroll_connected = True

    def _handle_infinite_scroll(self, value):
        if self._copy_height <= 0:
            return
        bar = self._scroll_area.verticalScrollBar()
        if value <= 0:
            bar.blockSignals(True)
            bar.setValue(value + self._copy_height)
            bar.blockSignals(False)
        elif value >= bar.maximum():
            bar.blockSignals(True)
            bar.setValue(value - self._copy_height)
            bar.blockSignals(False)

    # ---------- hover ----------

    def _all_live_cards(self):
        """Todas las LauncherCard vivas, de cualquiera de los modos. Sale
        de una lista mantenida a mano (ver _wire_card), no de recorrer el
        arbol de widgets: se consulta varias veces por segundo."""
        return list(self._live_cards)

    def _resync_all_hover_states(self):
        """Pone el hover de todas las tarjetas de acuerdo con la posicion
        real del cursor. Apaga las que quedaron prendidas y, con un
        movimiento de cursor a su misma posicion, hace que Qt entregue el
        enterEvent a la que ahora esta debajo."""
        if self._shutting_down:
            return
        pos = QCursor.pos()
        hovered_widget = QApplication.widgetAt(pos)
        for card in self._live_cards:
            try:
                card.force_unhover_if_stale(hovered_widget)
            except RuntimeError:
                pass
        # Solo si el cursor esta sobre esta ventana: no se toca el cursor
        # del usuario mientras trabaja en otra aplicacion.
        if self.isVisible() and self.frameGeometry().contains(pos):
            QCursor.setPos(pos)

    def _check_stale_hover(self):
        """Red de seguridad periodica: un leaveEvent tambien se puede
        perder sin scroll de por medio. Solo apaga lo que quedo prendido
        (sin mover el cursor: corre varias veces por segundo)."""
        hovered_widget = QApplication.widgetAt(QCursor.pos())
        for card in self._live_cards:
            try:
                card.force_unhover_if_stale(hovered_widget)
            except RuntimeError:
                pass  # tarjeta destruida por una reconstruccion en curso

    # =================================================================
    # Busqueda y teclado
    # =================================================================

    def _on_search_changed(self, text: str):
        self._search_query = text
        if text.strip():
            self._search_debounce.start()  # reinicia el plazo en cada tecla
        else:
            self._search_debounce.stop()
            self._refresh_layout()         # limpiar se aplica al instante

    def _update_navigation(self, groups: list, searching: bool, query_changed: bool):
        self._nav_entries = [e for g in groups for e in g["launchers"]]
        ids = [e.get("id") for e in self._nav_entries]
        if searching:
            # El mejor resultado queda seleccionado: Enter lo abre.
            if query_changed or self._selected_id not in ids:
                self._selected_id = ids[0] if ids else None
        elif query_changed or self._selected_id not in ids:
            self._selected_id = None

    def _apply_selection(self):
        for card in self._live_cards:
            try:
                card.set_selected(
                    self._selected_id is not None and card.entry.get("id") == self._selected_id
                )
            except RuntimeError:
                pass

    def _move_selection(self, delta: int):
        ids = [e.get("id") for e in self._nav_entries]
        if not ids:
            return
        if self._selected_id in ids:
            index = ids.index(self._selected_id) + delta
        else:
            index = 0 if delta > 0 else len(ids) - 1
        self._selected_id = ids[max(0, min(len(ids) - 1, index))]
        self._scroll_to_selected()
        self._apply_selection()

    def _scroll_to_selected(self):
        bar = self._scroll_area.verticalScrollBar()
        if self._virtual_list is not None:
            row = self._virtual_list.row_of(self._selected_id)
            if row is None:
                return
            y, height = row
            viewport_h = self._scroll_area.viewport().height()
            if y < bar.value():
                bar.setValue(max(0, y - self._virtual_rows[1]))
            elif y + height > bar.value() + viewport_h:
                bar.setValue(y + height - viewport_h)
            return
        if not self._copies:
            return
        # En modo bucle se usa la copia del medio.
        copy_index = _MIDDLE_COPY_INDEX if len(self._copies) == _NUM_COPIES else 0
        copy_widget = self._copies[copy_index]
        for card in self._live_cards:
            try:
                if card.entry.get("id") == self._selected_id and card.parentWidget() is copy_widget:
                    self._scroll_area.ensureWidgetVisible(card, 0, 24)
                    return
            except RuntimeError:
                pass

    def _launch_selected(self):
        """Enter: abre la seleccionada (con busqueda, el mejor resultado)."""
        self._search_debounce.stop()
        if self._search_query.strip() != (self._layout_query or "") and search.tokenize(self._search_query):
            self._refresh_layout()  # Enter llego antes que el debounce
        if self._selected_id is not None:
            self._launch(self._selected_id)

    def _handle_nav_key(self, key) -> bool:
        if key == Qt.Key.Key_Down:
            self._move_selection(1)
        elif key == Qt.Key.Key_Up:
            self._move_selection(-1)
        elif key == Qt.Key.Key_PageDown:
            self._move_selection(6)
        elif key == Qt.Key.Key_PageUp:
            self._move_selection(-6)
        else:
            return False
        return True

    def eventFilter(self, obj, event):
        # Flechas dentro del buscador: mueven la seleccion de la lista.
        if obj is self._search_box and event.type() == QEvent.Type.KeyPress:
            if self._handle_nav_key(event.key()):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        if self._handle_nav_key(key):
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Con el foco en el buscador ya lo atendio returnPressed (el
            # QLineEdit deja pasar la tecla hacia aca despues de emitirla).
            if not self._search_box.hasFocus():
                self._launch_selected()
            return
        # Escribir con el foco fuera del buscador: el texto va al buscador.
        text = event.text()
        blocked = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        if text and text.isprintable() and not (event.modifiers() & blocked):
            self._search_box.setFocus()
            self._search_box.insert(text)
            return
        super().keyPressEvent(event)

    # =================================================================
    # Acciones sobre una app
    # =================================================================

    def _on_card_clicked(self, entry_id: str):
        if self._drag_moved:
            return  # se solto el boton al terminar de arrastrar la ventana
        self._launch(entry_id)

    def _launch(self, entry_id: str):
        now = time.monotonic()
        last_id, last_time = self._last_launch
        if entry_id == last_id and now - last_time < _DOUBLE_LAUNCH_GUARD_S:
            return
        self._last_launch = (entry_id, now)

        name = self._entry_name(entry_id)
        if self.launcher_manager.launch(entry_id) is None:
            self._last_launch = (None, 0.0)  # que se pueda reintentar ya
            self._notify(
                f"No se pudo abrir {name}. Puede que ya no esté instalada.",
                toast.ERROR, tray=True,
            )
            return
        # La ventana no se cierra sola al lanzar: decision de producto.
        self._notify(f"Abriendo {name}…")

    def _on_remove_requested(self, entry_id: str):
        if self._drag_moved:
            return
        name = self._entry_name(entry_id)
        if not self.launcher_manager.hide_entry(entry_id):
            return
        QTimer.singleShot(0, self._refresh_layout)
        self._notify(
            f"{name} quitada de la lista", toast.INFO,
            action_text="Deshacer", on_action=lambda: self._undo_remove(entry_id),
        )

    def _undo_remove(self, entry_id: str):
        if self.launcher_manager.unhide_entry(entry_id):
            self._refresh_layout()
            self._notify(f"{self._entry_name(entry_id)} restaurada", toast.SUCCESS)

    def _on_favorite_toggled(self, entry_id: str, favorite: bool):
        if not self.launcher_manager.set_favorite(entry_id, favorite):
            return
        QTimer.singleShot(0, self._refresh_layout)  # ademas reordena
        name = self._entry_name(entry_id)
        self._notify(
            f"★ {name} marcada como favorita" if favorite else f"{name} quitada de favoritas",
            toast.SUCCESS if favorite else toast.INFO,
        )

    def _on_background_image_changed(self, entry_id: str, path: str):
        if not self.launcher_manager.set_hover_background(entry_id, path):
            return
        QTimer.singleShot(0, self._refresh_layout)
        self._notify(
            f"Imagen de fondo asignada a {self._entry_name(entry_id)}" if path
            else f"Imagen de fondo quitada de {self._entry_name(entry_id)}",
            toast.SUCCESS if path else toast.INFO,
        )

    def _on_background_pick_requested(self, entry_id: str):
        # El dialogo se abre en el siguiente ciclo y con ESTA ventana
        # como padre, no la tarjeta (ver el docstring del modulo).
        QTimer.singleShot(0, lambda: self._pick_background_for(entry_id))

    def _pick_background_for(self, entry_id: str):
        if self._dialog_open or self._shutting_down:
            return
        self._dialog_open = True
        try:
            path, _selected_filter = QFileDialog.getOpenFileName(
                self, "Elegir imagen de fondo", "", _IMAGE_FILTER
            )
        finally:
            self._dialog_open = False
        if path:
            self._on_background_image_changed(entry_id, path)

    # ---------- categorias ----------

    def _category_choices(self, entry_id: str):
        """Para el submenu "Mover a categoria" de una tarjeta: las
        categorias y en cual esta la app ahora."""
        return (
            self.launcher_manager.categories(),
            self.launcher_manager.category_of(entry_id),
        )

    def _category_title(self, group_id: str) -> str:
        for category in self.launcher_manager.categories():
            if category.get("group_id") == group_id:
                return _short(category.get("title"), 24)
        return "la categoría"

    def _on_category_move_requested(self, entry_id: str, group_id: str):
        if not self.launcher_manager.move_entry_to_category(entry_id, group_id):
            return
        QTimer.singleShot(0, self._refresh_layout)
        self._notify(
            f"{self._entry_name(entry_id)} movida a {self._category_title(group_id)}",
            toast.SUCCESS,
        )

    def _on_new_category_requested(self, entry_id: str):
        QTimer.singleShot(0, lambda: self._prompt_new_category_for(entry_id))

    def _prompt_new_category_for(self, entry_id: str):
        if self._dialog_open or self._shutting_down:
            return
        self._dialog_open = True
        try:
            name = ask_category_name(
                self, self.launcher_manager, "Nueva categoría", "Nombre de la categoría:"
            )
        finally:
            self._dialog_open = False
        if name is None:
            return
        try:
            group_id = self.launcher_manager.create_category(name)
        except ValueError as e:  # el nombre se tomo mientras el dialogo estaba abierto
            self._notify(str(e), toast.ERROR)
            return
        self.launcher_manager.move_entry_to_category(entry_id, group_id)
        self._refresh_layout()
        self._notify(
            f"{self._entry_name(entry_id)} movida a {self._category_title(group_id)}",
            toast.SUCCESS,
        )

    # ---------- panel ampliado ----------

    def _on_expand_requested(self, card):
        self._active_expand_card = card
        height_px = self.settings.get("animation", {}).get("expand_overlay_height_px", 220)
        self._expand_overlay.show_for_card(card, self, height_px)

    def _on_collapse_requested(self):
        # Un respiro: el mouse puede estar viajando de la tarjeta al
        # panel, que esta fuera de la ventana.
        QTimer.singleShot(150, self._maybe_hide_overlay)

    def _maybe_hide_overlay(self):
        """Cierra el panel si el cursor no esta ni sobre el ni sobre la
        tarjeta que lo abrio. Se consulta la posicion real del cursor:
        underMouse() puede quedar desactualizado (ver el modulo)."""
        if not self._expand_overlay.isVisible():
            return
        hovered_widget = QApplication.widgetAt(QCursor.pos())
        if self._widget_is_or_contains(self._expand_overlay, hovered_widget):
            return
        card = self._active_expand_card
        if card is not None:
            try:
                if self._widget_is_or_contains(card, hovered_widget):
                    return
            except RuntimeError:
                pass  # la tarjeta ya no existe (la lista se reconstruyo)
        self._expand_overlay.hide_animated()
        self._active_expand_card = None

    @staticmethod
    def _widget_is_or_contains(container, widget):
        while widget is not None:
            if widget is container:
                return True
            widget = widget.parentWidget()
        return False

    # =================================================================
    # Agregar app y Configuracion
    # =================================================================

    def _on_add_app_clicked(self):
        if self._drag_moved or self._dialog_open:
            return
        self._dialog_open = True
        dialog = AddAppDialog(self, categories=self.launcher_manager.categories())
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._dialog_open = False
        entry = dialog.result_entry if accepted else None
        group_id = dialog.result_group_id if accepted else None
        dialog.deleteLater()  # tiene padre: sin esto viviria hasta cerrar el programa
        if not entry:
            return

        self.launcher_manager.add_manual_entry(entry, group_id=group_id)
        QTimer.singleShot(0, self._refresh_layout)
        self._notify(f"{_short(entry.get('name'))} agregada", toast.SUCCESS)

        # La entrada ya esta guardada y visible con el icono generico; el
        # icono real se extrae en otro hilo y la lista se refresca luego.
        entry_id = entry.get("id")
        if entry_id:
            thread, worker = start_icon_resolve(
                self.launcher_manager,
                entry_id,
                on_finished=self._on_icon_resolved,
                on_failed=self._on_icon_resolve_failed,
            )
            self._icon_resolve_jobs.append((thread, worker))
            thread.finished.connect(lambda t=thread: self._on_icon_resolve_job_done(t))

    def _on_icon_resolve_job_done(self, thread):
        self._icon_resolve_jobs = [
            (t, w) for (t, w) in self._icon_resolve_jobs if t is not thread
        ]

    def _on_icon_resolved(self, changed: bool):
        if changed:
            self._refresh_layout()

    def _on_icon_resolve_failed(self, message: str):
        debug_log(f"No se pudo resolver el icono de la app agregada: {message}")

    def _on_settings_clicked(self):
        if self._drag_moved or self._dialog_open:
            return
        self._dialog_open = True
        dialog = SettingsWindow(self.launcher_manager, self)
        try:
            saved = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._dialog_open = False
        dialog.deleteLater()
        # Se relee y refresca siempre, aunque se cancele: restaurar apps
        # ocultas y editar categorias se aplican al momento en el dialogo.
        self.settings = load_settings()
        QTimer.singleShot(0, lambda: self._apply_settings_reload(saved))

    def _apply_settings_reload(self, saved: bool = False):
        self._apply_window_flags()
        width = self.settings.get("window", {}).get("width", 380)
        if width != self.width():
            self.setFixedWidth(width)
        self._reload_hotkey_if_changed()
        self._refresh_layout()
        if saved:
            self._notify("Configuración guardada", toast.SUCCESS)

    def _reload_hotkey_if_changed(self):
        new_hotkey_str = self.settings.get("hotkey_toggle", "ctrl+alt+space")
        if new_hotkey_str == self._hotkey_str:
            return
        self._global_hotkey.unregister()
        self._hotkey_str = new_hotkey_str
        self._global_hotkey = self._register_hotkey(new_hotkey_str)

    # =================================================================
    # Tamano y arrastre de la ventana
    # =================================================================

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._virtual_list is not None:
            bar = self._scroll_area.verticalScrollBar()
            self._virtual_list.update_window(bar.value(), self._scroll_area.viewport().height())
            self._apply_selection()
        if hasattr(self, "_toast") and self._toast.isVisible():
            self._toast.reposition()

    # La ventana no tiene barra de titulo: se arrastra desde cualquier
    # parte. El arrastre empieza recien al superar el umbral del sistema,
    # y el clic con que termina no abre la tarjeta que quedo debajo.

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_pos = self._press_pos - self.frameGeometry().topLeft()
            self._drag_moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            pos = event.globalPosition().toPoint()
            if not self._drag_moved:
                moved = (pos - self._press_pos).manhattanLength()
                self._drag_moved = moved >= QApplication.startDragDistance()
            if self._drag_moved:
                self.move(pos - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_moved:
            self._save_position()
            # Se limpia en el siguiente ciclo: el 'clicked' de la tarjeta
            # bajo el cursor se procesa antes y tiene que verlo en True.
            QTimer.singleShot(0, self._clear_drag_flag)
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _clear_drag_flag(self):
        self._drag_moved = False
