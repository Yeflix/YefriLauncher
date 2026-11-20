"""
scan_worker.py
-----------------
Corre LauncherManager.refresh() (Steam + accesos directos + apps de
Microsoft Store + extraccion de iconos) en un QThread aparte, para no
bloquear la ventana al iniciar -- el escaneo puede tardar varios
segundos con Start Menus grandes.

Tambien expone start_icon_resolve(), el mismo patron pero para resolver
en background el icono de UNA entrada agregada a mano (ver
LauncherManager.resolve_manual_icon) -- evita que ExtractIconEx /
SHGetFileInfo corran en el hilo de UI justo al agregar una app.
"""

from PySide6.QtCore import QObject, QThread, Signal


class ScanWorker(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(self, launcher_manager, scan_steam=True, scan_shortcuts=True, scan_uwp=True,
                 auto_rules=None):
        super().__init__()
        self._launcher_manager = launcher_manager
        self._scan_steam = scan_steam
        self._scan_shortcuts = scan_shortcuts
        self._scan_uwp = scan_uwp
        self._auto_rules = auto_rules

    def run(self):
        try:
            self._launcher_manager.refresh(
                scan_steam=self._scan_steam,
                scan_shortcuts=self._scan_shortcuts,
                scan_uwp=self._scan_uwp,
                auto_rules=self._auto_rules,
            )
        except Exception as e:  # noqa: BLE001 - queremos capturar cualquier fallo
            self.failed.emit(str(e))
            return
        self.finished.emit()


def start_scan(launcher_manager, on_finished, on_failed=None,
                scan_steam=True, scan_shortcuts=True, scan_uwp=True, auto_rules=None):
    """Crea el QThread + worker, los conecta, y los arranca.

    scan_steam/scan_shortcuts/scan_uwp reflejan settings["detection"]
    (ver core/config_manager.py y ui/settings_window.py) -- permiten
    desactivar una fuente de deteccion puntual sin tocar codigo.
    auto_rules: ids de las reglas de categorizacion automatica activas
    (settings["auto_categories"], ver core/auto_categories.py); None =
    las que vienen activas por defecto.

    Devuelve (thread, worker): el llamador DEBE guardar esta referencia
    en un atributo (ej. self._scan_thread) mientras dure el escaneo, o
    Python los recolecta como basura y el hilo se corta a mitad de
    camino."""
    thread = QThread()
    worker = ScanWorker(
        launcher_manager,
        scan_steam=scan_steam,
        scan_shortcuts=scan_shortcuts,
        scan_uwp=scan_uwp,
        auto_rules=auto_rules,
    )
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    if on_failed:
        worker.failed.connect(on_failed)

    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(thread.quit)
    worker.failed.connect(worker.deleteLater)  # antes solo se limpiaba en el camino de exito
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker


class IconResolveWorker(QObject):
    finished = Signal(bool)  # True si el icono cambio de verdad
    failed = Signal(str)

    def __init__(self, launcher_manager, entry_id: str):
        super().__init__()
        self._launcher_manager = launcher_manager
        self._entry_id = entry_id

    def run(self):
        try:
            changed = self._launcher_manager.resolve_manual_icon(self._entry_id)
        except Exception as e:  # noqa: BLE001 - no tirar abajo el hilo por esto
            self.failed.emit(str(e))
            return
        self.finished.emit(changed)


def start_icon_resolve(launcher_manager, entry_id: str, on_finished, on_failed=None):
    """Igual que start_scan, pero para resolver el icono de UNA entrada
    puntual (agregada a mano) sin bloquear el hilo de UI.

    Devuelve (thread, worker): el llamador debe guardar la referencia
    mientras dure (ver nota de start_scan)."""
    thread = QThread()
    worker = IconResolveWorker(launcher_manager, entry_id)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    if on_failed:
        worker.failed.connect(on_failed)

    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(thread.quit)
    worker.failed.connect(worker.deleteLater)  # antes solo se limpiaba en el camino de exito
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker
