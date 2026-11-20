"""
icon_extractor.py
-------------------
Obtiene el icono de cada app y lo guarda como PNG en
cache/extracted_icons/, con un nombre derivado de su origen para no
volver a extraerlo en cada escaneo.

* Programas (.exe / IconLocation de un .lnk): ExtractIconEx con el
  indice del acceso directo -> ExtractIconEx con indice 0 ->
  SHGetFileInfo (el icono "asociado" que muestra el Explorador).
* Steam: la imagen-icono de appcache/librarycache/<appid>/.
* Microsoft Store: el logo declarado en AppxManifest.xml.

Reglas de la cache
--------------------
* La cache se consulta ANTES de hacer el trabajo caro.
* Cada PNG se escribe a un temporal y se renombra al final (ver
  _save_png): si el programa se cierra a mitad de un escaneo no queda
  un archivo truncado que despues se tomaria por bueno.
* Los iconos de programas se renderizan al tamano de icono del sistema
  (32 px al 100%, 48 px al 150%...), y los de Steam/Store a 64 px, para
  que se vean nitidos con el escalado de pantalla de Windows.
* prune_cache() borra los PNG que ya no usa ninguna app.
"""

import ctypes
from ctypes import wintypes
import hashlib
import os
import re
import threading
import time
from xml.etree import ElementTree

import win32gui
import win32ui
from PIL import Image

# Sufijo del nombre de archivo en cache. Cambiarlo invalida todo lo
# cacheado por una version anterior (los archivos viejos los limpia
# prune_cache).
_CACHE_VERSION = "v2"

# Lado, en pixeles, de los iconos que salen de una imagen (Steam, Store).
IMAGE_ICON_PX = 64

_SM_CXICON = 11
_DI_NORMAL = 0x0003

_SHGFI_ICON = 0x100
_SHGFI_LARGEICON = 0x0
_SHGFI_SMALLICON = 0x1


class _SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


def _system_icon_size() -> int:
    """Lado del icono 'grande' del sistema. Depende del escalado de
    pantalla: 32 al 100%, 40 al 125%, 48 al 150%, 64 al 200%. Los HICON
    que devuelven ExtractIconEx/SHGetFileInfo vienen en ese tamano."""
    try:
        size = int(ctypes.windll.user32.GetSystemMetrics(_SM_CXICON))
    except Exception:
        size = 0
    return max(32, min(256, size or 32))


def _cache_file(cache_dir: str, key: str) -> str:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{digest}_{_CACHE_VERSION}.png")


def _is_cached(cache_path: str) -> bool:
    try:
        return os.path.getsize(cache_path) > 0
    except OSError:
        return False


def _save_png(img: Image.Image, cache_path: str) -> None:
    """Escritura atomica (temporal + os.replace). El nombre del temporal
    incluye proceso e hilo: varias extracciones corren en paralelo."""
    tmp_path = f"{cache_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        img.save(tmp_path, "PNG")
        os.replace(tmp_path, cache_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _save_image_as_icon(source_path: str, cache_path: str, size: int) -> bool:
    try:
        img = Image.open(source_path).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        _save_png(img, cache_path)
        return True
    except Exception:
        return False


def prune_cache(cache_dir: str, keep_paths, min_age_s: float = 3600) -> int:
    """Borra de la cache los archivos que no estan en 'keep_paths' (los
    iconos que usa alguna app). Solo toca .png/.tmp con mas de
    'min_age_s' de antiguedad, para no pisar una extraccion en curso.
    Devuelve cuantos borro. Nunca lanza."""
    removed = 0
    try:
        keep = {os.path.normcase(os.path.abspath(p)) for p in keep_paths if p}
        now = time.time()
        for name in os.listdir(cache_dir):
            if not name.lower().endswith((".png", ".tmp")):
                continue
            path = os.path.join(cache_dir, name)
            if os.path.normcase(os.path.abspath(path)) in keep:
                continue
            try:
                if now - os.path.getmtime(path) < min_age_s:
                    continue
                os.remove(path)
                removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def _hicon_to_pil(hicon, size: int) -> Image.Image:
    """Renderiza un HICON a una imagen PIL de size x size. Los tres
    recursos GDI que se piden (DC de pantalla, DC de memoria, bitmap) se
    liberan siempre en el finally: la app vive semanas en la bandeja y
    una fuga por icono se acumula."""
    screen_dc_handle = win32gui.GetDC(0)
    hdc_screen = win32ui.CreateDCFromHandle(screen_dc_handle)
    hdc_mem = None
    hbmp = None
    try:
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc_screen, size, size)
        hdc_mem = hdc_screen.CreateCompatibleDC()
        hdc_mem.SelectObject(hbmp)
        try:
            # Con tamano explicito: DrawIcon a secas dibuja al tamano de
            # icono del sistema, que con escalado de pantalla no es 32 y
            # no coincidiria con el bitmap.
            win32gui.DrawIconEx(
                hdc_mem.GetSafeHdc(), 0, 0, hicon, size, size, 0, None, _DI_NORMAL
            )
        except Exception:
            hdc_mem.DrawIcon((0, 0), hicon)

        bmpinfo = hbmp.GetInfo()
        bmpstr = hbmp.GetBitmapBits(True)
        return Image.frombuffer(
            "RGBA",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr, "raw", "BGRA", 0, 1,
        )
    finally:
        # Orden: DC de memoria (deselecciona el bitmap), bitmap, y el DC
        # de pantalla con ReleaseDC (se obtuvo con GetDC, no se borra).
        if hdc_mem is not None:
            hdc_mem.DeleteDC()
        if hbmp is not None:
            win32gui.DeleteObject(hbmp.GetHandle())
        win32gui.ReleaseDC(0, screen_dc_handle)


def _extract_via_shgetfileinfo(path: str, size: int):
    """Ultimo recurso: le pide a Windows el icono 'asociado' al archivo
    (el mismo que se veria en el Explorador). Retorna un HICON (hay que
    liberarlo con DestroyIcon) o None."""
    info = _SHFILEINFO()
    flags = _SHGFI_ICON | (_SHGFI_LARGEICON if size > 16 else _SHGFI_SMALLICON)
    try:
        result = ctypes.windll.shell32.SHGetFileInfoW(
            path, 0, ctypes.byref(info), ctypes.sizeof(info), flags
        )
    except Exception:
        return None
    if not result or not info.hIcon:
        return None
    return info.hIcon


def _parse_icon_location(icon_location: str):
    """'C:\\ruta\\archivo.exe,3' -> ('C:\\ruta\\archivo.exe', 3).
    Si no trae indice, asume 0."""
    if "," in icon_location:
        path, idx = icon_location.rsplit(",", 1)
        try:
            index = int(idx.strip())
        except ValueError:
            index = 0
        return path.strip(), index
    return icon_location.strip(), 0


def _save_hicon(hicon, cache_path: str, size: int) -> bool:
    try:
        img = _hicon_to_pil(hicon, size=size)
        _save_png(img, cache_path)
        return True
    except Exception:
        return False


def extract_icon(icon_location: str, cache_dir: str, size: int = None):
    """Retorna la ruta al PNG cacheado, o None si no se pudo extraer.
    icon_location puede ser 'archivo.exe' o 'archivo.exe,indice'
    (formato que devuelve Shortcut.IconLocation de un .lnk).
    size: lado en pixeles; por defecto, el tamano de icono del sistema."""
    if not icon_location:
        return None

    exe_path, index = _parse_icon_location(icon_location)
    if not exe_path or not os.path.exists(exe_path):
        return None

    os.makedirs(cache_dir, exist_ok=True)
    cache_path = _cache_file(cache_dir, f"{exe_path.lower()}|{index}")
    if _is_cached(cache_path):
        return cache_path

    if size is None:
        size = _system_icon_size()

    try:
        large, small = win32gui.ExtractIconEx(exe_path, index)
    except Exception:
        large, small = [], []

    if not large and not small and index != 0:
        # Algunos accesos directos traen un indice obsoleto/invalido;
        # como intento intermedio, probamos el primer icono del archivo.
        try:
            large, small = win32gui.ExtractIconEx(exe_path, 0)
        except Exception:
            large, small = [], []

    if large or small:
        hicon = large[0] if large else small[0]
        saved = _save_hicon(hicon, cache_path, size)
        for handle in (large or []) + (small or []):
            try:
                win32gui.DestroyIcon(handle)
            except Exception:
                pass
        if saved:
            return cache_path

    # Ultimo recurso: icono asociado por Windows (SHGetFileInfo).
    hicon = _extract_via_shgetfileinfo(exe_path, size)
    if hicon:
        saved = _save_hicon(hicon, cache_path, size)
        try:
            win32gui.DestroyIcon(hicon)
        except Exception:
            pass
        if saved:
            return cache_path

    return None


def extract_steam_icon(steam_path: str, appid: str, cache_dir: str, size: int = IMAGE_ICON_PX):
    """Icono especifico de un juego de Steam.

    El cliente moderno de Steam cachea, por cada appid, una carpeta
    appcache/librarycache/<appid>/ con varias imagenes de nombre FIJO
    (header.jpg, logo.png, library_hero.jpg, library_hero_blur.jpg) MAS
    un archivo nombrado con un hash largo (ej.
    'c9036837d770245e72fc968c04a77966594930b5.jpg') que es el icono
    real -- se identifica por descarte: es el archivo que no coincide
    con ninguno de los nombres conocidos.

    (Intentos anteriores con steam/games/<appid>.ico y
    appcache/librarycache/<appid>_icon.jpg no funcionaban: el primero
    nombra los .ico con un hash, no con el appid, y el segundo formato
    de ruta ya no existe en versiones modernas del cliente.)
    """
    if not steam_path or not appid:
        return None

    os.makedirs(cache_dir, exist_ok=True)
    cache_path = _cache_file(cache_dir, f"steam_icon_{appid}")
    if _is_cached(cache_path):
        return cache_path

    folder = os.path.join(steam_path, "appcache", "librarycache", str(appid))
    if not os.path.isdir(folder):
        return None

    known_names = {
        "header.jpg", "header.png",
        "logo.png", "logo.jpg",
        "library_hero.jpg", "library_hero.png",
        "library_hero_blur.jpg", "library_hero_blur.png",
    }
    candidates = []
    for fname in os.listdir(folder):
        lower = fname.lower()
        if lower in known_names:
            continue
        if lower.startswith("library_600x900") or lower.startswith("library_capsule"):
            continue
        if lower.endswith((".jpg", ".jpeg", ".png")):
            candidates.append(fname)

    if not candidates:
        return None

    # Si por algun motivo queda mas de un candidato, el nombre-hash real
    # de Valve es mucho mas largo que cualquier nombre "normal".
    candidates.sort(key=len, reverse=True)
    icon_source = os.path.join(folder, candidates[0])

    return cache_path if _save_image_as_icon(icon_source, cache_path, size) else None


# ---------------------------------------------------------------------
# Iconos de apps empaquetadas (UWP / Microsoft Store)
# ---------------------------------------------------------------------
# core/uwp_detector.py detecta estas apps via Get-StartApps, que solo da
# Name + AppID (no icono). El logo real vive declarado dentro de
# AppxManifest.xml, en la carpeta de instalacion del paquete
# (InstallLocation, que uwp_detector SI puede averiguar cruzando con
# Get-AppxPackage).

def extract_uwp_icon(install_location: str, cache_dir: str, size: int = IMAGE_ICON_PX):
    """Icono de una app empaquetada, a partir de su AppxManifest.xml.
    Retorna la ruta al PNG cacheado, o None si algun paso de la cadena
    falla (paquete sin manifest legible, asset no encontrado, etc. --
    nunca debe tirar abajo el escaneo completo por una sola app)."""
    if not install_location or not os.path.isdir(install_location):
        return None

    # La clave sale de install_location (y no del asset, que recien se
    # conoce despues de leer el manifest) para poder consultar la cache
    # antes de hacer ese trabajo.
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = _cache_file(cache_dir, f"uwp_icon_{install_location.lower()}")
    if _is_cached(cache_path):
        return cache_path

    manifest_path = os.path.join(install_location, "AppxManifest.xml")
    if not os.path.exists(manifest_path):
        return None

    logo_rel = _read_manifest_logo(manifest_path)
    if not logo_rel:
        return None

    asset_path = _resolve_scaled_asset(install_location, logo_rel)
    if not asset_path:
        return None

    return cache_path if _save_image_as_icon(asset_path, cache_path, size) else None


def _read_manifest_logo(manifest_path: str):
    """Lee el atributo Square44x44Logo (o Square150x150Logo como
    fallback, si el paquete no declara el chico) del nodo
    VisualElements de AppxManifest.xml.

    Se recorre el arbol ignorando el namespace de cada tag (el prefijo
    real varia entre 'uap', 'uap3', 'uap5', etc. segun con que version
    del SDK de Windows se empaqueto la app -- comparar por namespace
    exacto rompe con paquetes mas nuevos/viejos que el que se probo)."""
    try:
        tree = ElementTree.parse(manifest_path)
    except Exception:
        return None

    for elem in tree.getroot().iter():
        tag = elem.tag.rsplit("}", 1)[-1]  # '{namespace}VisualElements' -> 'VisualElements'
        if tag != "VisualElements":
            continue
        for attr in ("Square44x44Logo", "Square150x150Logo"):
            value = elem.attrib.get(attr)
            if value:
                return value
    return None


def _resolve_scaled_asset(install_location: str, logo_rel: str):
    """El nombre declarado en el manifest (ej. 'Assets\\Logo.png') casi
    nunca existe tal cual en disco: Windows empaqueta los assets con un
    sufijo de escala (Logo.scale-200.png) o de tamano de destino
    (Logo.targetsize-256.png). Se busca en la carpeta del asset
    cualquier archivo que comparta el mismo nombre base y se elige el
    de mayor resolucion disponible (ver _scale_hint).

    AppxManifest.xml declara la ruta SIEMPRE con backslash ('Assets\\Logo.png',
    formato Windows nativo) sin importar en que SO se inspeccione el
    archivo despues -- se normalizan ambas barras a os.sep en vez de
    asumir que el separador nativo del sistema actual coincide con el
    que trae el manifest."""
    normalized = logo_rel.replace("\\", os.sep).replace("/", os.sep)
    full_path = os.path.join(install_location, normalized)
    if os.path.exists(full_path):
        return full_path

    directory = os.path.dirname(full_path)
    # OJO: el nombre base se calcula sobre full_path (ya normalizado),
    # no sobre logo_rel -- usar logo_rel aca haria que
    # os.path.basename() no reconociera el backslash como separador en
    # cualquier SO donde os.sep no sea '\\', y devolviera el string
    # entero ('Assets\\Logo44.png') como si fuera un unico nombre de
    # archivo.
    base_name = os.path.splitext(os.path.basename(full_path))[0]
    if not os.path.isdir(directory):
        return None

    candidates = [
        os.path.join(directory, fname)
        for fname in os.listdir(directory)
        if fname.lower().startswith(base_name.lower())
        and fname.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    if not candidates:
        return None

    candidates.sort(key=_scale_hint, reverse=True)
    return candidates[0]


def _scale_hint(path: str) -> int:
    """Numero de escala/tamano en el nombre de archivo (200 en
    'Logo.scale-200.png', 256 en 'Logo.targetsize-256.png'), para poder
    elegir el candidato de mayor resolucion. 0 si el nombre no trae
    ninguno (se sigue prefiriendo un candidato CON numero antes que uno
    sin el, gracias a reverse=True en el sort)."""
    name = os.path.basename(path).lower()
    match = re.search(r"(?:scale|targetsize)-(\d+)", name)
    return int(match.group(1)) if match else 0
