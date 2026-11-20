"""
paths.py
----------
Punto UNICO de verdad para las carpetas de datos de la app (config/,
cache/), resueltas siempre respecto a donde vive el propio proyecto (o
el .exe, si esta empaquetado), nunca respecto al directorio de trabajo
(cwd) del proceso.

Por que importa
-----------------
config_manager.py y launcher_manager.py usaban rutas relativas sueltas
("config/settings.json", "config/launchers.json", "cache/extracted_icons")
sin resolverlas contra ningun punto fijo. Eso funciona perfecto cuando
se corre `python main.py` parado DENTRO de la carpeta del proyecto --
pero se rompe en cualquier otro escenario de lanzamiento: un acceso
directo de Windows sin "Iniciar en" apuntando a la carpeta correcta,
una entrada de inicio automatico, una Tarea Programada, etc. En esos
casos el cwd del proceso puede terminar siendo CUALQUIER otra carpeta
(el Escritorio, System32, la carpeta de inicio de Windows...), asi que
la app termina leyendo/escribiendo un config/launchers.json DISTINTO en
cada corrida -- o uno que directamente no existe todavia, asi que
arranca de cero. Eso es lo que se percibe como "la configuracion y las
imagenes se resetean cada vez que cierro y vuelvo a abrir el programa":
en realidad no se resetean, se estan usando archivos distintos cada vez.

Esta funcion resuelve la carpeta base contra el propio archivo fuente
(__file__) en vez del cwd -- y, pensando en el empaquetado a .exe con
PyInstaller (ver main.spec), tambien contempla el
caso "frozen" (sys.frozen), usando la carpeta del .exe real en vez de
sys._MEIPASS (que es una carpeta temporal DISTINTA en cada corrida con
--onefile, y hubiera reintroducido este mismo bug post-empaquetado).
"""

import os
import shutil
import sys

if getattr(sys, "frozen", False):
    # Empaquetado con PyInstaller: sys.executable es el .exe real que el
    # usuario ejecuto. sys._MEIPASS (si existe) es una carpeta temporal
    # de extraccion que cambia en cada corrida con --onefile -- NO sirve
    # como base estable para guardar datos persistentes del usuario.
    APP_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    # core/paths.py -> subir un nivel = raiz del proyecto (donde vive main.py)
    APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------
# Carpeta de DATOS DEL USUARIO (launchers.json, settings.json, debug.log,
# cache de iconos): separada a proposito de la carpeta del CODIGO.
#
# Por que: si los datos viven dentro del proyecto (APP_ROOT/config), cada
# vez que se reemplaza o se vuelve a descomprimir el proyecto -- para
# actualizar el codigo, restaurar una copia, mover la carpeta -- el
# launchers.json que viene en esa copia pisa al del usuario, y con el se
# van las imagenes de fondo, favoritas y categorias asignadas desde la
# ultima vez. Se guardaba bien; el que se perdia era el archivo. Con los
# datos en %APPDATA% se puede tirar y reemplazar la carpeta del proyecto
# (o el .exe) las veces que haga falta sin tocar nada del usuario.
#
# Prioridad:
#   1. Variable de entorno SPECTRUM_DATA_DIR (util para pruebas o para
#      una instalacion portable).
#   2. Windows: %APPDATA%\\SpectrumLauncher
#   3. Otros sistemas (solo desarrollo/tests): la propia carpeta del
#      proyecto, como antes.
# ---------------------------------------------------------------------
APP_NAME = "SpectrumLauncher"


def _resolve_data_dir() -> str:
    override = os.environ.get("SPECTRUM_DATA_DIR")
    if override:
        return os.path.abspath(override)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, APP_NAME)
    return APP_ROOT


DATA_DIR = _resolve_data_dir()

CONFIG_DIR = os.path.join(DATA_DIR, "config")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
LAUNCHERS_PATH = os.path.join(CONFIG_DIR, "launchers.json")
ICON_CACHE_DIR = os.path.join(CACHE_DIR, "extracted_icons")

# Donde vivian los datos antes de separarlos (junto al codigo).
LEGACY_CONFIG_DIR = os.path.join(APP_ROOT, "config")


def migrate_legacy_data(log=None) -> list:
    """Copia UNA sola vez los datos de la ubicacion vieja (APP_ROOT/config)
    a la nueva (CONFIG_DIR), para no perder lo que el usuario ya tenia.

    - Solo copia lo que todavia NO existe en el destino: nunca pisa datos
      que ya viven en la carpeta nueva.
    - Copia, no mueve: la carpeta vieja queda intacta como respaldo.
    - No hace nada si ambas rutas son la misma (Linux/tests) o si no hay
      nada que migrar. Nunca tira excepcion.

    Devuelve la lista de archivos copiados."""
    copied = []
    try:
        if os.path.abspath(LEGACY_CONFIG_DIR) == os.path.abspath(CONFIG_DIR):
            return copied
        if not os.path.isdir(LEGACY_CONFIG_DIR):
            return copied
        os.makedirs(CONFIG_DIR, exist_ok=True)
        for name in ("launchers.json", "settings.json"):
            src = os.path.join(LEGACY_CONFIG_DIR, name)
            dst = os.path.join(CONFIG_DIR, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                copied.append(name)
    except OSError as e:
        if log:
            log(f"migrate_legacy_data(): fallo ({e})")
        return copied
    if copied and log:
        log(f"migrate_legacy_data(): copiado {copied} de '{LEGACY_CONFIG_DIR}' a '{CONFIG_DIR}'")
    return copied
