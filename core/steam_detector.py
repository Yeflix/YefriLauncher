"""
steam_detector.py
------------------
Localiza la instalacion de Steam y enumera los juegos instalados
(en cualquiera de las bibliotecas configuradas, no solo la principal).
"""

import os

import vdf
import winreg


def get_steam_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        return os.path.normpath(path)
    except (FileNotFoundError, OSError):
        return None


def _get_library_folders(steam_path: str) -> list:
    libs = [steam_path]
    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.exists(vdf_path):
        return libs

    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            data = vdf.load(f)
    except Exception:
        return libs

    folders = data.get("libraryfolders", {})
    for entry in folders.values():
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if path:
            norm = os.path.normpath(path)
            if norm not in libs:
                libs.append(norm)
    return libs


def scan_steam_library(steam_path: str = None) -> list:
    """Retorna una lista de dicts compatibles con el schema de launchers.json.

    Acepta un steam_path ya resuelto para que el llamador (refresh() en
    launcher_manager.py, que tambien necesita steam_path para
    extract_steam_icon) no tenga que leer el registro de Windows dos
    veces en el mismo escaneo. Si no se pasa nada, se resuelve aqui
    mismo (comportamiento anterior, usado por los tests y por quien
    llame a esta funcion de forma aislada)."""
    if steam_path is None:
        steam_path = get_steam_path()
    if not steam_path:
        return []

    results = []
    for lib in _get_library_folders(steam_path):
        steamapps = os.path.join(lib, "steamapps")
        if not os.path.isdir(steamapps):
            continue

        for filename in os.listdir(steamapps):
            if not (filename.startswith("appmanifest_") and filename.endswith(".acf")):
                continue

            manifest_path = os.path.join(steamapps, filename)
            try:
                with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = vdf.load(f)
            except Exception:
                continue

            app_state = data.get("AppState", {})
            appid = app_state.get("appid")
            name = app_state.get("name")
            if not appid or not name:
                continue

            # 228980 = "Steamworks Common Redistributables", se instala junto
            # con casi cualquier juego pero no es un juego en si mismo.
            if str(appid) == "228980" or "redistributable" in name.lower():
                continue

            results.append({
                "id": f"steam_{appid}",
                "name": name,
                "type": "steam",
                "target": f"steam://rungameid/{appid}",
                "icon": "auto",
                "source": "auto",
                "close_after_launch": True,
            })

    return results
