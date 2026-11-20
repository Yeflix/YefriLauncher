"""
Punto de entrada de SPECTRUM Launcher (version Python).

El escaneo de Steam + accesos directos corre en un hilo aparte
(MainWindow.start_background_scan) para no bloquear la aparicion de la
ventana. Si hay datos en cache de una corrida anterior
(config/launchers.json), se muestran de inmediato mientras el escaneo
fresco corre por atras.
"""

import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.config_manager import load_settings
from core.debug_log import log as debug_log
from core.launcher_manager import LauncherManager
from core.paths import CONFIG_DIR, migrate_legacy_data
from core.single_instance import SingleInstanceGuard
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    # Fusion respeta los QSS personalizados de forma consistente. El estilo
    # nativo de Windows (windowsvista/windows11) ignora varias propiedades
    # (fondos de QGroupBox, colores de seleccion, etc.), lo que causaba que
    # el panel de Configuracion se viera con colores incorrectos/inconsistentes.
    app.setStyle("Fusion")
    # La ventana principal ahora vive en la bandeja del sistema: cerrarla
    # (Escape, click en una app con close_after_launch, etc.) solo la
    # oculta, no debe terminar el proceso. La unica salida real es
    # "Cerrar" desde el menu de la bandeja (MainWindow._on_quit).
    app.setQuitOnLastWindowClosed(False)

    # Una sola instancia a la vez: dos copias corriendo se pisan la
    # escritura de launchers.json entre si (el lock de LauncherManager es
    # intra-proceso), duplican el icono de bandeja, y dejan el atajo
    # global de la segunda muerto en silencio. Ver core/single_instance.py.
    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        # Ya habia una corriendo; try_acquire() le pidio que se muestre.
        # Salimos sin abrir nada, asi volver a lanzar el .exe se comporta
        # como "traer la ventana al frente".
        return 0

    # Los datos del usuario viven en %APPDATA%\SpectrumLauncher (ver
    # core/paths.py), no junto al codigo. La primera vez se copian desde
    # la carpeta config/ vieja del proyecto, antes de cargar nada.
    migrate_legacy_data(log=debug_log)
    debug_log(f"datos del usuario en: {CONFIG_DIR}")

    settings = load_settings()
    manager = LauncherManager()  # carga lo que haya en cache, todavia sin escanear

    window = MainWindow(manager, settings)
    guard.show_requested.connect(window.show_and_raise)
    # Cualquier camino que termine el bucle de eventos (Cerrar en la
    # bandeja, Ctrl+C, cierre de sesion de Windows...) pasa por el mismo
    # cierre ordenado. shutdown() es idempotente.
    app.aboutToQuit.connect(window.shutdown)
    app.aboutToQuit.connect(guard.release)
    window.show()
    window.start_background_scan()

    _enable_ctrl_c(app)

    code = app.exec()
    debug_log("main(): bucle de eventos terminado, cerrando proceso")
    return code


def _enable_ctrl_c(app):
    """Hace que Ctrl+C en la terminal cierre el programa.

    Mientras Qt corre su bucle en C++, Python nunca recupera el control y
    no llega a procesar SIGINT: sin esto, la unica forma de cerrar un
    `python main.py` era cerrar la terminal. El timer vacio devuelve el
    control al interprete unas veces por segundo para que el manejador de
    la senal pueda correr."""
    def _request_quit(*_args):
        app.quit()

    signal.signal(signal.SIGINT, _request_quit)
    for name in ("SIGBREAK", "SIGTERM"):  # SIGBREAK = Ctrl+Pausa en Windows
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _request_quit)

    wake = QTimer(app)
    wake.timeout.connect(lambda: None)
    wake.start(250)
    app._signal_wake_timer = wake  # evita que lo recolecte el GC


def _terminate(code: int):
    """Termina el proceso YA, sin esperar a nada mas.

    Un sys.exit() normal espera a que terminen los hilos no-daemon del
    ThreadPoolExecutor (extraccion de iconos) y, si quedo un QThread vivo,
    Qt aborta con 'Destroyed while thread is still running'. Para este
    punto el cierre ordenado (MainWindow.shutdown) ya corrio y todo lo del
    usuario esta en disco: launchers.json y settings.json se escriben al
    instante y de forma atomica en cada cambio, asi que salir sin esperar
    no pierde nada."""
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == "__main__":
    _terminate(main())
