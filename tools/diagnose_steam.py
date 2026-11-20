"""
diagnose_steam.py
-------------------
Script de diagnostico standalone (no depende del resto del proyecto)
para averiguar por que scan_steam_library() no encuentra juegos.

Ejecutar desde la raiz del proyecto:
    python tools/diagnose_steam.py

Pega la salida completa para que podamos ajustar steam_detector.py.
"""

import os
import sys

import winreg

try:
    import vdf
except ImportError:
    print("ERROR: falta instalar 'vdf' -> pip install vdf")
    sys.exit(1)


def get_steam_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        return os.path.normpath(path)
    except Exception as e:
        print(f"[registro] ERROR leyendo HKCU\\Software\\Valve\\Steam -> SteamPath: {e!r}")
        return None


print("=" * 70)
steam_path = get_steam_path()
print("SteamPath detectado:", steam_path)

if not steam_path:
    print("No se pudo leer la clave del registro. Revisa si Steam.exe alguna")
    print("vez se abrio e inicio sesion (la clave se crea al primer login).")
    sys.exit(0)

print("Existe la carpeta?:", os.path.isdir(steam_path))

vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
print("\nRuta esperada de libraryfolders.vdf:", vdf_path)
print("Existe?:", os.path.exists(vdf_path))

if not os.path.exists(vdf_path):
    print("No existe ese archivo -> revisa manualmente si existe con otro")
    print("nombre dentro de:", os.path.join(steam_path, "steamapps"))
    sys.exit(0)

print("\n--- Contenido crudo de libraryfolders.vdf ---")
with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
    raw = f.read()
print(raw[:2000])

print("\n--- Parseado con la libreria vdf ---")
try:
    with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
        data = vdf.load(f)
    print(data)
except Exception as e:
    print(f"ERROR al parsear con vdf.load(): {e!r}")
    sys.exit(0)

folders = data.get("libraryfolders", {})
libs = [steam_path]
for entry in folders.values():
    if isinstance(entry, dict) and entry.get("path"):
        libs.append(os.path.normpath(entry["path"]))

print("\nBibliotecas encontradas:", libs)

print("\n--- Buscando appmanifest_*.acf en cada biblioteca ---")
for lib in libs:
    steamapps = os.path.join(lib, "steamapps")
    print(f"\n[{steamapps}] existe?: {os.path.isdir(steamapps)}")
    if not os.path.isdir(steamapps):
        continue
    manifests = [f for f in os.listdir(steamapps) if f.startswith("appmanifest_")]
    print(f"  appmanifest_*.acf encontrados: {len(manifests)}")
    for m in manifests[:10]:
        print("   -", m)
