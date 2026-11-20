"""
diagnose_steam_icons.py
--------------------------
Los dos intentos anteriores para encontrar el icono de un juego de
Steam (steam/games/<appid>.ico y appcache/librarycache/<appid>_icon.jpg)
fallaron para TODOS los juegos -- Steam debe haber cambiado el formato
de cache en versiones mas nuevas del cliente. En vez de adivinar una
tercera ruta a ciegas, este script explora lo que realmente existe en
tu instalacion para poder ajustar la estrategia con datos reales.

Ejecutar desde la raiz del proyecto:
    python tools/diagnose_steam_icons.py [appid]

Si no pasas un appid, usa el primero que encuentre instalado.
Pegame TODA la salida.
"""

import os
import sys

import winreg


def get_steam_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        return os.path.normpath(path)
    except Exception as e:
        print(f"No se pudo leer el registro: {e}")
        return None


def find_first_appid(steam_path):
    steamapps = os.path.join(steam_path, "steamapps")
    if not os.path.isdir(steamapps):
        return None
    for f in os.listdir(steamapps):
        if f.startswith("appmanifest_") and f.endswith(".acf"):
            return f[len("appmanifest_"):-len(".acf")]
    return None


def explore(path, appid, max_list=30):
    print(f"\n--- {path} ---")
    exists = os.path.isdir(path)
    print("Existe?:", exists)
    if not exists:
        return

    all_files = os.listdir(path)
    matches = [f for f in all_files if appid and appid in f]
    print(f"Archivos/carpetas que contienen '{appid}': {matches[:max_list]}")
    if not matches:
        print(f"No hay coincidencias directas. Primeros {max_list} nombres en la carpeta")
        print("(para ver el patron real que usa tu version de Steam):")
        print(all_files[:max_list])


def main():
    steam_path = get_steam_path()
    print("SteamPath:", steam_path)
    if not steam_path:
        return

    appid = sys.argv[1] if len(sys.argv) > 1 else find_first_appid(steam_path)
    print("Usando appid:", appid)
    if not appid:
        print("No se encontro ningun appmanifest_*.acf, no se puede continuar.")
        return

    explore(os.path.join(steam_path, "steam", "games"), appid)
    explore(os.path.join(steam_path, "appcache", "librarycache"), appid)
    explore(os.path.join(steam_path, "appcache", "librarycache", appid), appid)

    # Por si el juego tiene su propia carpeta de instalacion con algun
    # icono suelto (algunos juegos traen un .ico al lado del .exe).
    steamapps_common = os.path.join(steam_path, "steamapps", "common")
    print(f"\n--- {steamapps_common} ---")
    print("Existe?:", os.path.isdir(steamapps_common))
    if os.path.isdir(steamapps_common):
        print("Carpetas de juegos instalados (primeras 15):")
        print(os.listdir(steamapps_common)[:15])


if __name__ == "__main__":
    main()
