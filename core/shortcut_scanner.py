"""
shortcut_scanner.py
--------------------
Escanea los accesos directos (.lnk) del Menu Inicio y del Escritorio
(del usuario y de todos los usuarios) y los convierte en entradas de
launchers.json.

Que guarda cada entrada
-------------------------
* 'target': el .exe al que apunta el acceso directo. Es lo que
  identifica a la app (id, icono, reglas de categoria, busqueda).
* 'launch': el propio .lnk. Es lo que se ejecuta (ver
  LauncherManager.launch), para respetar los argumentos, la carpeta de
  trabajo y el "ejecutar como administrador" del acceso directo.

Identidad
-----------
El id es un hash de la ruta normalizada del .exe. Si el acceso directo
lleva argumentos, entran en el hash: dos accesos al mismo ejecutable con
argumentos distintos (apps web de Chrome/Edge, herramientas de Python o
Java) son apps distintas. En ese caso la entrada trae ademas un
'legacy_id' temporal (el hash solo del .exe, que es el id que tenia en
versiones anteriores) para que LauncherManager.refresh() le traspase la
personalizacion; no se guarda en disco.
"""

import hashlib
import os

import win32com.client

# Nombres de archivo que casi seguro no son "abrir el programa".
_EXCLUDE_KEYWORDS = (
    "uninstall", "desinstalar", "unins0", "readme", "leeme",
    "help", "ayuda", "documentation", "website", "web site", "sitio web",
)

# Herramientas del propio Windows (Lupa, Narrador, regedit...): no son
# "programas instalados por el usuario".
_WINDIR = os.environ.get("WINDIR", r"C:\Windows")

# Excepcion dentro de la carpeta de Windows: los accesos directos de
# programas instalados con MSI apuntan a un ejecutable-icono guardado en
# C:\Windows\Installer. Son programas normales.
_MSI_INSTALLER_FRAGMENT = "\\installer\\"

# Apps "de fabrica" que viven en Program Files, fuera de C:\Windows.
_LEGACY_WINDOWS_APPS = (
    r"\internet explorer\iexplore.exe",
    r"\windows media player\wmplayer.exe",
    r"\windows nt\accessories\wordpad.exe",
    r"\common files\microsoft shared\ink\mip.exe",
)

# Carpetas especiales de WScript.Shell, en orden de preferencia: si la
# misma app aparece en dos, gana el nombre de la primera.
_SPECIAL_FOLDERS = ("Programs", "AllUsersPrograms", "Desktop", "AllUsersDesktop")


def _is_windows_system_tool(target: str) -> bool:
    norm = os.path.normpath(target).lower().replace("/", "\\")
    windir = os.path.normpath(_WINDIR).lower().replace("/", "\\").rstrip("\\") + "\\"
    if norm.startswith(windir):
        return _MSI_INSTALLER_FRAGMENT not in norm
    return any(legacy in norm for legacy in _LEGACY_WINDOWS_APPS)


def _make_id(target: str, arguments: str = "") -> str:
    """Estable entre escaneos: normpath + minusculas colapsan las
    variaciones de formato de una misma ruta. Sin argumentos, el id es
    el mismo que en versiones anteriores."""
    normalized = os.path.normpath(target).lower()
    arguments = (arguments or "").strip().lower()
    if arguments:
        normalized = f"{normalized}|{arguments}"
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:10]
    return f"shortcut_{digest}"


def _scan_dirs(shell) -> list:
    """Carpetas a recorrer. Se le preguntan a Windows (el Escritorio
    puede estar redirigido a OneDrive, y existe un Escritorio publico);
    las rutas armadas con variables de entorno quedan como respaldo."""
    candidates = []
    for name in _SPECIAL_FOLDERS:
        try:
            candidates.append(str(shell.SpecialFolders(name) or ""))
        except Exception:
            pass
    candidates += [
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        os.path.join(os.environ.get("PUBLIC", ""), "Desktop"),
    ]
    result, seen = [], set()
    for path in candidates:
        if not path or not os.path.isabs(path) or not os.path.isdir(path):
            continue
        key = os.path.normcase(os.path.normpath(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def scan_shortcuts() -> list:
    """Lista de entradas compatibles con launchers.json. Lanza una
    excepcion si no se puede hablar con el shell de Windows: quien llama
    (LauncherManager.refresh) lo trata como "esta fuente fallo" y
    conserva lo que ya tenia."""
    # COM hay que inicializarlo en cada hilo que lo usa, y esto corre en
    # el hilo del escaneo, no en el principal.
    com_initialized = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        com_initialized = True
    except Exception:
        pythoncom = None

    shell = None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        return _scan(shell)
    finally:
        shell = None  # soltar el objeto COM antes de CoUninitialize
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _scan(shell) -> list:
    results = []
    seen = set()

    for base_dir in _scan_dirs(shell):
        for root, _dirs, files in os.walk(base_dir):
            for fname in files:
                lower_name = fname.lower()
                if not lower_name.endswith(".lnk"):
                    continue
                if any(kw in lower_name for kw in _EXCLUDE_KEYWORDS):
                    continue

                lnk_path = os.path.join(root, fname)
                try:
                    shortcut = shell.CreateShortcut(lnk_path)
                    target = shortcut.Targetpath
                    icon_location = shortcut.IconLocation
                    arguments = shortcut.Arguments
                except Exception:
                    continue

                if not target or not target.lower().endswith(".exe"):
                    continue
                if not os.path.exists(target):
                    continue
                if _is_windows_system_tool(target):
                    continue

                arguments = (arguments or "").strip()
                key = (os.path.normpath(target).lower(), arguments.lower())
                if key in seen:
                    continue
                seen.add(key)

                entry = {
                    "id": _make_id(target, arguments),
                    "name": os.path.splitext(fname)[0],
                    "type": "shortcut",
                    "target": target,
                    "launch": lnk_path,
                    "icon_location": icon_location or target,
                    "icon": "auto",
                    "source": "auto",
                    "close_after_launch": True,
                }
                if arguments:
                    entry["legacy_id"] = _make_id(target)
                results.append(entry)

    return results
