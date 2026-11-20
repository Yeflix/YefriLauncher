"""
debug_log.py
--------------
Logging minimo a archivo, compartido por los modulos que antes
reportaban fallas con print() -- invisible si el programa corre
empaquetado sin consola (el caso tipico de un .exe hecho con PyInstaller
en modo --windowed): nada se ve, y no hay forma de saber despues que
paso. Escribe al mismo archivo que ya usa LauncherManager
(core/launcher_manager.py tiene su propio _log() porque necesita poder
apuntar a un config_path custom en los tests; este modulo es para todo
lo demas que no tiene una instancia de LauncherManager a mano) para que
toda la informacion de diagnostico de una sesion quede junta en un solo
lugar.
"""

import os
import threading
import time

from core.paths import CONFIG_DIR

_LOG_PATH = os.path.join(CONFIG_DIR, "debug.log")
_LOG_MAX_BYTES = 200_000
# La extraccion de iconos en paralelo (ver core/launcher_manager.py,
# _resolve_entry_icon) puede llamar a log() desde varios hilos del
# ThreadPoolExecutor a la vez si mas de uno falla junto -- sin este
# lock, dos hilos podrian pisarse la rotacion del archivo (ambos
# deciden borrarlo a la vez) o, en el peor caso, escribir al mismo
# tiempo de una forma que el sistema operativo no garantice atomica.
_lock = threading.Lock()


def log(message: str):
    """Nunca tira excepcion -- un log que rompe la app que se supone
    tiene que ayudar a diagnosticar seria peor que no tener log."""
    try:
        with _lock:
            if os.path.exists(_LOG_PATH) and os.path.getsize(_LOG_PATH) > _LOG_MAX_BYTES:
                os.remove(_LOG_PATH)
            directory = os.path.dirname(_LOG_PATH)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass
