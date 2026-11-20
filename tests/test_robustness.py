"""
test_robustness.py
--------------------
Lo que protege los datos del usuario frente a un escaneo que sale mal,
un archivo editado a mano o un cierre a destiempo: fuentes que fallan,
apps que desaparecen y vuelven, accesos directos con argumentos, cache
de iconos y settings.json con valores invalidos.

Corre en cualquier sistema (ver conftest.py).
"""

import json
import os
import subprocess
import time

import pytest
from PIL import Image

from core import config_manager, icon_extractor, launcher_manager, shortcut_scanner, uwp_detector


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("core.steam_detector.scan_steam_library", lambda *a, **k: [])
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [])
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])
    return launcher_manager.LauncherManager(
        config_path=str(tmp_path / "launchers.json"),
        cache_dir=str(tmp_path / "cache"),
    )


def _entry(eid, name, kind="shortcut", **extra):
    base = {
        "id": eid, "name": name, "type": kind, "target": f"/{eid}.exe",
        "icon": "auto", "source": "auto", "close_after_launch": True,
    }
    if kind == "shortcut":
        base["icon_location"] = f"/{eid}.exe"
    if kind == "uwp":
        base["install_location"] = ""
    base.update(extra)
    return base


def _find(manager, eid):
    return next((e for e in manager._all_entries() if e["id"] == eid), None)


def _personalize(manager, eid):
    manager.set_favorite(eid, True)
    manager.set_hover_background(eid, "C:/img/fondo.png")
    gid = manager.create_category("Trabajo")
    manager.move_entry_to_category(eid, gid)
    return gid


# ---------------------------------------------------------------------
# Una fuente que falla no borra nada
# ---------------------------------------------------------------------

def test_fuente_que_devuelve_none_conserva_sus_apps(manager, monkeypatch):
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [_entry("u1", "Calculadora", "uwp")])
    manager.refresh(auto_rules=[])
    gid = _personalize(manager, "u1")

    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: None)  # PowerShell no respondio
    summary = manager.refresh(auto_rules=[])

    entry = _find(manager, "u1")
    assert entry is not None and entry["favorite"] is True
    assert entry["hover_background"] == "C:/img/fondo.png"
    assert manager.category_of("u1") == gid
    assert summary["failed"] == ["uwp"] and summary["removed"] == 0


def test_fuente_que_lanza_excepcion_no_aborta_el_escaneo(manager, monkeypatch):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [_entry("s1", "Editor")])
    manager.refresh(auto_rules=[])

    def roto():
        raise RuntimeError("el shell no contesta")

    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", roto)
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [_entry("u1", "Fotos", "uwp")])
    summary = manager.refresh(auto_rules=[])

    assert _find(manager, "s1") is not None      # la fuente rota conserva lo suyo
    assert _find(manager, "u1") is not None      # y las demas fuentes siguen funcionando
    assert summary["failed"] == ["shortcuts"] and summary["added"] == 1


def test_solo_se_conservan_las_apps_de_la_fuente_que_fallo(manager, monkeypatch):
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [_entry("u1", "Fotos", "uwp")])
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [_entry("s1", "Editor")])
    manager.refresh(auto_rules=[])

    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: None)
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])  # s1 se desinstalo de verdad
    manager.refresh(auto_rules=[])

    assert _find(manager, "u1") is not None
    assert _find(manager, "s1") is None


# ---------------------------------------------------------------------
# Una app que desaparece y vuelve recupera su personalizacion
# ---------------------------------------------------------------------

def test_app_que_desaparece_y_vuelve_recupera_todo(manager, monkeypatch, tmp_path):
    monkeypatch.setattr("core.steam_detector.scan_steam_library",
                        lambda *a, **k: [_entry("steam_10", "Juego", "steam")])
    manager.refresh(auto_rules=[])
    gid = _personalize(manager, "steam_10")
    manager.hide_entry("steam_10")

    # El disco con la biblioteca se desconecto: el juego ya no se detecta.
    monkeypatch.setattr("core.steam_detector.scan_steam_library", lambda *a, **k: [])
    summary = manager.refresh(auto_rules=[])
    assert _find(manager, "steam_10") is None and summary["removed"] == 1

    # Lo recordado sobrevive a un reinicio del programa.
    reloaded = launcher_manager.LauncherManager(
        config_path=str(tmp_path / "launchers.json"), cache_dir=str(tmp_path / "cache")
    )
    monkeypatch.setattr("core.steam_detector.scan_steam_library",
                        lambda *a, **k: [_entry("steam_10", "Juego", "steam")])
    reloaded.refresh(auto_rules=[])

    entry = _find(reloaded, "steam_10")
    assert entry["favorite"] is True and entry["hidden"] is True
    assert entry["hover_background"] == "C:/img/fondo.png"
    assert entry["category_locked"] is True
    assert reloaded.category_of("steam_10") == gid
    assert "remembered" not in reloaded.data     # ya se uso: no queda basura


def test_desactivar_una_fuente_quita_sus_apps_pero_recuerda_lo_suyo(manager, monkeypatch):
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [_entry("u1", "Fotos", "uwp")])
    manager.refresh(auto_rules=[])
    manager.set_favorite("u1", True)

    manager.refresh(scan_uwp=False, auto_rules=[])
    assert _find(manager, "u1") is None          # el usuario pidio no ver esa fuente

    manager.refresh(auto_rules=[])
    assert _find(manager, "u1")["favorite"] is True


def test_una_app_sin_personalizar_no_deja_rastro_al_desaparecer(manager, monkeypatch):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [_entry("s1", "Editor")])
    manager.refresh(auto_rules=[])
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])
    manager.refresh(auto_rules=[])
    assert "remembered" not in manager.data


def test_remembered_con_basura_se_normaliza(tmp_path):
    path = tmp_path / "launchers.json"
    path.write_text(json.dumps({"groups": [], "remembered": ["no", "es", "un", "objeto"]}), encoding="utf-8")
    m = launcher_manager.LauncherManager(config_path=str(path), cache_dir=str(tmp_path / "c"))
    assert "remembered" not in m.data


def test_lo_recordado_tiene_tope(manager, monkeypatch):
    monkeypatch.setattr(launcher_manager, "_MAX_REMEMBERED", 3)
    apps = [_entry(f"s{i}", f"App {i}") for i in range(6)]
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: list(map(dict, apps)))
    manager.refresh(auto_rules=[])
    for i in range(6):
        manager.set_favorite(f"s{i}", True)
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])
    manager.refresh(auto_rules=[])
    assert len(manager.data["remembered"]) == 3


# ---------------------------------------------------------------------
# refresh(): resumen y escritura solo si hubo cambios
# ---------------------------------------------------------------------

def test_refresh_sin_cambios_no_reescribe_el_archivo(manager, monkeypatch, tmp_path):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [_entry("s1", "Editor")])
    first = manager.refresh(auto_rules=[])
    assert first == {"changed": True, "added": 1, "removed": 0, "failed": []}

    path = tmp_path / "launchers.json"
    stamp = os.stat(path).st_mtime_ns
    before = _find(manager, "s1")
    time.sleep(0.02)
    second = manager.refresh(auto_rules=[])

    assert second["changed"] is False and second["added"] == 0
    assert os.stat(path).st_mtime_ns == stamp
    assert _find(manager, "s1") is before        # la interfaz conserva el mismo objeto
    assert manager.last_refresh == second


def test_los_datos_de_trabajo_del_escaneo_no_se_guardan(manager, monkeypatch, tmp_path):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts",
                        lambda: [_entry("s1", "Editor", legacy_id="shortcut_viejo")])
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [_entry("u1", "Fotos", "uwp")])
    manager.refresh(auto_rules=[])
    saved = (tmp_path / "launchers.json").read_text(encoding="utf-8")
    for clave in ("icon_location", "install_location", "legacy_id"):
        assert clave not in saved


# ---------------------------------------------------------------------
# Accesos directos: lanzar por el .lnk, argumentos e identidad
# ---------------------------------------------------------------------

def test_launch_abre_el_lnk_y_no_el_exe(manager, monkeypatch, tmp_path):
    lnk = tmp_path / "Editor.lnk"
    lnk.write_bytes(b"")
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts",
                        lambda: [_entry("s1", "Editor", launch=str(lnk))])
    manager.refresh(auto_rules=[])
    abiertos = []
    monkeypatch.setattr(os, "startfile", abiertos.append, raising=False)

    assert manager.launch("s1") is not None
    assert abiertos == [str(lnk)]


def test_launch_cae_al_exe_si_el_lnk_ya_no_existe(manager, monkeypatch, tmp_path):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts",
                        lambda: [_entry("s1", "Editor", launch=str(tmp_path / "borrado.lnk"))])
    manager.refresh(auto_rules=[])
    abiertos = []
    monkeypatch.setattr(os, "startfile", abiertos.append, raising=False)

    manager.launch("s1")
    assert abiertos == ["/s1.exe"]


def test_launch_de_una_entrada_sin_destino_no_propaga(manager, monkeypatch):
    manager.data["groups"][0]["launchers"].append({"id": "rota", "name": "Rota"})
    monkeypatch.setattr(os, "startfile", lambda p: None, raising=False)
    assert manager.launch("rota") is None


def test_id_de_shortcut_con_argumentos():
    exe = r"C:\Apps\chrome_proxy.exe"
    sin_args = shortcut_scanner._make_id(exe)
    assert shortcut_scanner._make_id(exe, "") == sin_args          # compatible con versiones anteriores
    assert shortcut_scanner._make_id(exe, "  ") == sin_args
    a = shortcut_scanner._make_id(exe, "--app-id=aaa")
    b = shortcut_scanner._make_id(exe, "--app-id=bbb")
    assert len({sin_args, a, b}) == 3
    assert shortcut_scanner._make_id(exe, "--APP-ID=aaa ") == a    # estable ante formato


def test_un_acceso_con_argumentos_hereda_lo_de_su_id_anterior(manager, monkeypatch):
    # Version anterior: la app web se guardo con el id "solo del exe".
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [_entry("shortcut_viejo", "Gmail")])
    manager.refresh(auto_rules=[])
    gid = _personalize(manager, "shortcut_viejo")

    # Version nueva: el mismo acceso llega con id propio y legacy_id.
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [
        _entry("shortcut_gmail", "Gmail", legacy_id="shortcut_viejo"),
        _entry("shortcut_youtube", "YouTube", legacy_id="shortcut_viejo"),
    ])
    manager.refresh(auto_rules=[])

    assert _find(manager, "shortcut_viejo") is None
    gmail, youtube = _find(manager, "shortcut_gmail"), _find(manager, "shortcut_youtube")
    assert gmail["favorite"] is True and manager.category_of("shortcut_gmail") == gid
    assert "favorite" not in youtube             # solo hereda uno
    assert "remembered" not in manager.data


def test_herramientas_de_windows_y_excepcion_de_msi(monkeypatch):
    monkeypatch.setattr(shortcut_scanner, "_WINDIR", r"C:\Windows")
    tool = shortcut_scanner._is_windows_system_tool
    assert tool(r"C:\Windows\System32\notepad.exe")
    assert tool(r"C:\Program Files\Internet Explorer\iexplore.exe")
    assert not tool(r"C:\Windows\Installer\{GUID}\icono.exe")      # programa instalado con MSI
    assert not tool(r"C:\WindowsApps2\programa.exe")               # no es la carpeta de Windows
    assert not tool(r"C:\Program Files\Editor\editor.exe")


class _FakeShortcut:
    def __init__(self, target, arguments=""):
        self.Targetpath, self.Arguments, self.IconLocation = target, arguments, ""


class _FakeShell:
    def __init__(self, folders, shortcuts):
        self._folders, self._shortcuts = folders, shortcuts

    def SpecialFolders(self, name):
        return self._folders.get(name, "")

    def CreateShortcut(self, path):
        return self._shortcuts[os.path.basename(path)]


def test_scan_shortcuts_guarda_el_lnk_y_separa_por_argumentos(monkeypatch, tmp_path):
    menu, desktop = tmp_path / "menu", tmp_path / "escritorio"
    menu.mkdir()
    desktop.mkdir()
    exe, proxy = tmp_path / "editor.exe", tmp_path / "proxy.exe"
    exe.write_bytes(b"")
    proxy.write_bytes(b"")
    for folder, name in ((menu, "Editor.lnk"), (desktop, "Editor (2).lnk"), (menu, "Gmail.lnk"),
                         (menu, "YouTube.lnk"), (menu, "Desinstalar Editor.lnk"), (menu, "Roto.lnk")):
        (folder / name).write_bytes(b"")
    shell = _FakeShell(
        {"Programs": str(menu), "Desktop": str(desktop)},
        {
            "Editor.lnk": _FakeShortcut(str(exe)),
            "Editor (2).lnk": _FakeShortcut(str(exe)),                 # mismo exe sin argumentos: duplicado
            "Gmail.lnk": _FakeShortcut(str(proxy), "--app-id=gmail"),
            "YouTube.lnk": _FakeShortcut(str(proxy), "--app-id=youtube"),
            "Desinstalar Editor.lnk": _FakeShortcut(str(exe)),
            "Roto.lnk": _FakeShortcut(str(tmp_path / "no_existe.exe")),
        },
    )
    for var in ("APPDATA", "ProgramData", "USERPROFILE", "PUBLIC"):
        monkeypatch.setenv(var, str(tmp_path / "vacio"))
    monkeypatch.setattr(shortcut_scanner.win32com.client, "Dispatch", lambda *a, **k: shell)

    found = {e["name"]: e for e in shortcut_scanner.scan_shortcuts()}

    assert sorted(found) == ["Editor", "Gmail", "YouTube"]
    assert found["Editor"]["launch"] == str(menu / "Editor.lnk")       # se lanza el acceso directo
    assert found["Editor"]["target"] == str(exe)
    assert "legacy_id" not in found["Editor"]
    assert found["Gmail"]["id"] != found["YouTube"]["id"]
    assert found["Gmail"]["legacy_id"] == found["YouTube"]["legacy_id"] == shortcut_scanner._make_id(str(proxy))


# ---------------------------------------------------------------------
# Microsoft Store: fallo vs. lista vacia
# ---------------------------------------------------------------------

class _Proc:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, b""


def test_scan_uwp_distingue_fallo_de_lista_vacia(monkeypatch):
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("powershell", 15)

    monkeypatch.setattr("core.uwp_detector.subprocess.run", timeout)
    assert uwp_detector.scan_uwp_apps() is None

    monkeypatch.setattr("core.uwp_detector.subprocess.run", lambda *a, **k: _Proc(returncode=1))
    assert uwp_detector.scan_uwp_apps() is None

    monkeypatch.setattr("core.uwp_detector.subprocess.run",
                        lambda *a, **k: _Proc("esto no es JSON".encode("utf-16-le")))
    assert uwp_detector.scan_uwp_apps() is None

    monkeypatch.setattr("core.uwp_detector.subprocess.run", lambda *a, **k: _Proc(b""))
    assert uwp_detector.scan_uwp_apps() == []


def test_el_script_no_interpola_el_paquete_pegado_a_un_signo_de_pregunta():
    """En PowerShell, "$PackageFullName?..." entre comillas dobles se lee
    como la variable '$PackageFullName?' ('?' es valido en nombres) y el
    nombre del paquete queda vacio."""
    assert '"@{$PackageFullName?' not in uwp_detector._PS_SCRIPT
    assert "$PackageFullName + '?'" in uwp_detector._PS_SCRIPT


# ---------------------------------------------------------------------
# Cache de iconos
# ---------------------------------------------------------------------

def test_guardar_icono_es_atomico_y_no_deja_temporales(tmp_path):
    cache = tmp_path / "icono_v2.png"
    icon_extractor._save_png(Image.new("RGBA", (8, 8)), str(cache))
    assert cache.exists() and Image.open(cache).size == (8, 8)
    assert [p.name for p in tmp_path.iterdir()] == ["icono_v2.png"]


def test_un_archivo_vacio_en_cache_no_se_da_por_bueno(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    steam = tmp_path / "steam"
    folder = steam / "appcache" / "librarycache" / "730"
    folder.mkdir(parents=True)
    Image.new("RGB", (100, 100), "red").save(folder / ("c9036837d770245e72fc968c04a77966594930b5.jpg"))

    # Un PNG que quedo vacio por un cierre a destiempo.
    broken = icon_extractor._cache_file(str(cache_dir), "steam_icon_730")
    open(broken, "wb").close()
    assert not icon_extractor._is_cached(broken)

    result = icon_extractor.extract_steam_icon(str(steam), "730", str(cache_dir))

    assert result == broken                       # se regenero en el mismo lugar
    side = icon_extractor.IMAGE_ICON_PX
    assert Image.open(result).size == (side, side)
    assert icon_extractor.extract_steam_icon(str(steam), "730", str(cache_dir)) == result   # ahora si, de cache


def test_prune_cache_borra_solo_huerfanos_viejos(tmp_path):
    usado, huerfano, reciente, ajeno = (tmp_path / n for n in ("usado.png", "viejo.png", "reciente.png", "notas.txt"))
    for path in (usado, huerfano, reciente, ajeno):
        path.write_bytes(b"x")
    viejo = time.time() - 7200
    for path in (usado, huerfano, ajeno):
        os.utime(path, (viejo, viejo))

    removed = icon_extractor.prune_cache(str(tmp_path), [str(usado)])

    assert removed == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notas.txt", "reciente.png", "usado.png"]
    assert icon_extractor.prune_cache(str(tmp_path / "no_existe"), []) == 0   # nunca lanza


# ---------------------------------------------------------------------
# settings.json con valores invalidos
# ---------------------------------------------------------------------

def _load(tmp_path, data):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return config_manager.load_settings(str(path))


def test_settings_con_tipos_equivocados_usa_los_valores_por_defecto(tmp_path):
    s = _load(tmp_path, {
        "window": 5,                                   # una seccion que no es un objeto
        "animation": {"duration_ms": "rapido", "easing": 7},
        "detection": {"scan_steam": "si"},
        "hotkey_toggle": None,
    })
    d = config_manager.DEFAULT_SETTINGS
    assert s["window"] == d["window"]
    assert s["animation"]["duration_ms"] == d["animation"]["duration_ms"]
    assert s["animation"]["easing"] == d["animation"]["easing"]
    assert s["detection"]["scan_steam"] is True
    assert s["hotkey_toggle"] == d["hotkey_toggle"]


def test_settings_recorta_numeros_y_opciones_fuera_de_rango(tmp_path):
    s = _load(tmp_path, {
        "window": {"width": 5000, "background_alpha": -3, "compact_card_height": 50.6, "sort_mode": "raro"},
        "animation": {"speed_multiplier": 9, "hover_slide_direction": "arriba"},
    })
    assert s["window"]["width"] == 600
    assert s["window"]["background_alpha"] == 80
    assert s["window"]["compact_card_height"] == 51 and isinstance(s["window"]["compact_card_height"], int)
    assert s["window"]["sort_mode"] == "favorites_first"
    assert s["animation"]["speed_multiplier"] == 2.0
    assert s["animation"]["hover_slide_direction"] == "right"


def test_settings_posicion_de_ventana_y_claves_desconocidas(tmp_path):
    s = _load(tmp_path, {"window": {"x": -1200, "y": 40, "futuro": "se conserva"}, "otra_seccion": {"a": 1}})
    assert (s["window"]["x"], s["window"]["y"]) == (-1200, 40)
    assert s["window"]["futuro"] == "se conserva" and s["otra_seccion"] == {"a": 1}

    s = _load(tmp_path, {"window": {"x": "izquierda", "y": True}})
    assert s["window"]["x"] is None and s["window"]["y"] is None


def test_settings_con_raiz_que_no_es_objeto(tmp_path):
    assert _load(tmp_path, ["no", "es", "un", "objeto"]) == config_manager.DEFAULT_SETTINGS
