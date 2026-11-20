"""
test_core.py
--------------
Tests de la capa core/, sin UI.

Por que existe este archivo
------------------------------
Durante el desarrollo se corrigieron varios bugs reales (persistencia de
la imagen de fondo, JSON corrupto que impedia arrancar, escritura no
atomica, perdida de personalizacion al re-agregar una app, fuga de
handles GDI, condicion de carrera entre el escaneo y la UI...). Cada uno
se valido en su momento con un script suelto que despues se perdia, asi
que no quedaba NADA que detectara si una de esas correcciones se rompia
mas adelante. Estos tests son esa red.

Cada test se llama segun el bug que previene, no segun la funcion que
toca -- la idea es que si uno falla, se entienda de inmediato que
regreso.

Como correrlos
-----------------
    python -m pytest tests/ -v

En Windows corren tal cual. Fuera de Windows hace falta stubear los
modulos nativos (win32gui, win32com, winreg, pythoncom); ver
tests/conftest.py.
"""

import json
import os
import threading
import time

import pytest

from core import config_manager, launcher_manager, shortcut_scanner, uwp_detector


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """LauncherManager aislado en un tmp_path, con los detectores
    mockeados para no depender de lo que haya instalado en la maquina."""
    monkeypatch.setattr("core.steam_detector.scan_steam_library", lambda *a, **k: [])
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [])
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])
    return launcher_manager.LauncherManager(
        config_path=str(tmp_path / "launchers.json"),
        cache_dir=str(tmp_path / "cache"),
    )


def _entry(eid, name, **extra):
    base = {
        "id": eid, "name": name, "type": "shortcut", "target": f"/{eid}.exe",
        "icon_location": f"/{eid}.exe", "icon": "auto", "source": "auto",
        "close_after_launch": True,
    }
    base.update(extra)
    return base


# --------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------

def test_refresh_no_pierde_la_imagen_de_fondo(manager, monkeypatch):
    """refresh() corre en CADA arranque. Antes reemplazaba por completo
    las entradas detectadas, y como los detectores no saben nada de
    hover_background, la imagen se perdia en el primer reinicio."""
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts",
                        lambda: [_entry("s1", "App")])
    manager.refresh()
    manager.set_hover_background("s1", "/img/fondo.png")

    manager.refresh()  # simula el arranque siguiente

    entry = next(e for e in manager._all_entries() if e["id"] == "s1")
    assert entry.get("hover_background") == "/img/fondo.png"


def test_refresh_preserva_apps_ocultas(manager, monkeypatch):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts",
                        lambda: [_entry("s1", "App")])
    manager.refresh()
    manager.hide_entry("s1")
    manager.refresh()
    assert next(e for e in manager._all_entries() if e["id"] == "s1").get("hidden") is True


def test_reagregar_app_manual_no_borra_su_personalizacion(manager):
    """Re-agregar sin querer el mismo ejecutable no debe perder la
    imagen de fondo ni el estado oculto."""
    manager.add_manual_entry(_entry("m1", "Mi App", source="manual"))
    manager.set_hover_background("m1", "/img/f.png")
    manager.hide_entry("m1")

    manager.add_manual_entry(_entry("m1", "Mi App", source="manual"))

    entry = next(e for e in manager._all_entries() if e["id"] == "m1")
    assert entry.get("hover_background") == "/img/f.png"
    assert entry.get("hidden") is True


def test_json_corrupto_no_impide_arrancar(tmp_path):
    """Un launchers.json truncado (proceso muerto a mitad de escritura)
    hacia que la app no volviera a abrir NUNCA hasta borrarlo a mano."""
    cp = tmp_path / "launchers.json"
    cp.write_text('{"groups": [{"launchers": [{"id": "x", "nam', encoding="utf-8")

    mgr = launcher_manager.LauncherManager(config_path=str(cp),
                                           cache_dir=str(tmp_path / "cache"))

    assert list(mgr._all_entries()) == []
    assert (tmp_path / "launchers.json.corrupt").exists(), "no se preservo copia para diagnosticar"


def test_settings_corrupto_no_impide_arrancar(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text('{"window": {"background_al', encoding="utf-8")
    settings = config_manager.load_settings(str(sp))
    assert settings["window"]["background_alpha"] == \
        config_manager.DEFAULT_SETTINGS["window"]["background_alpha"]


def test_guardado_es_atomico_sin_residuos(manager):
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    assert not os.path.exists(manager.config_path + ".tmp")
    with open(manager.config_path, encoding="utf-8") as f:
        json.load(f)  # no debe tirar


def test_settings_viejo_se_completa_con_defaults(tmp_path):
    """Un settings.json de una version anterior no debe quedar sin las
    claves nuevas (antes se devolvia el JSON tal cual)."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"window": {"always_on_top": False}}), encoding="utf-8")
    s = config_manager.load_settings(str(sp))
    assert s["window"]["always_on_top"] is False      # respeta lo que habia
    assert "detection" in s                            # completa lo que falta
    assert "sort_mode" in s["window"]


def test_load_settings_no_muta_los_defaults_globales(tmp_path):
    sp = tmp_path / "settings.json"
    s = config_manager.load_settings(str(sp))
    s["window"]["background_alpha"] = 999
    assert config_manager.DEFAULT_SETTINGS["window"]["background_alpha"] != 999


# --------------------------------------------------------------------
# Lanzamiento
# --------------------------------------------------------------------

def test_launch_con_target_roto_no_propaga_excepcion(manager, monkeypatch):
    """Un click en una app desinstalada crasheaba la app entera."""
    manager.add_manual_entry(_entry("m1", "Rota", source="manual"))
    monkeypatch.setattr(os, "startfile",
                        lambda p: (_ for _ in ()).throw(OSError(2, "no existe")),
                        raising=False)
    assert manager.launch("m1") is None


def test_launch_con_id_inexistente_no_propaga_excepcion(manager):
    assert manager.launch("no_existe") is None


# --------------------------------------------------------------------
# Orden y favoritas
# --------------------------------------------------------------------

def test_orden_alfabetico_respeta_acentos_y_enie(manager, monkeypatch):
    """'ámbar' debe caer antes que 'Blender', no despues de 'Zoom'
    (que es lo que pasa ordenando por codepoint Unicode)."""
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [
        _entry("s1", "Zoom"), _entry("s2", "ámbar"),
        _entry("s3", "Blender"), _entry("s4", "Ñandú"),
    ])
    manager.refresh()
    nombres = [e["name"] for e in manager.visible_groups("alphabetical")[0]["launchers"]]
    assert nombres == ["ámbar", "Blender", "Ñandú", "Zoom"]


def test_favoritas_van_primero(manager, monkeypatch):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [
        _entry("s1", "Audacity"), _entry("s2", "Zoom"),
    ])
    manager.refresh()
    manager.set_favorite("s2", True)
    nombres = [e["name"] for e in manager.visible_groups("favorites_first")[0]["launchers"]]
    assert nombres == ["Zoom", "Audacity"]


def test_desmarcar_favorita_no_deja_basura_en_el_json(manager):
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    manager.set_favorite("m1", True)
    manager.set_favorite("m1", False)
    saved = json.loads(open(manager.config_path, encoding="utf-8").read())
    assert all("favorite" not in e for e in saved["groups"][0]["launchers"])


def test_visible_groups_filtra_las_ocultas(manager):
    manager.add_manual_entry(_entry("m1", "Visible", source="manual"))
    manager.add_manual_entry(_entry("m2", "Oculta", source="manual"))
    manager.hide_entry("m2")
    nombres = [e["name"] for e in manager.visible_groups()[0]["launchers"]]
    assert nombres == ["Visible"]


# --------------------------------------------------------------------
# Concurrencia
# --------------------------------------------------------------------

def test_refresh_y_add_manual_concurrentes_no_se_pisan(manager, monkeypatch):
    """El escaneo corre en su propio hilo; si el usuario agrega una app
    mientras tanto, ninguno de los dos cambios debe perderse."""
    def scan_lento():
        time.sleep(0.2)
        return [_entry("s1", "Detectada")]
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", scan_lento)

    t = threading.Thread(target=manager.refresh)
    t.start()
    time.sleep(0.05)
    manager.add_manual_entry(_entry("m1", "Manual", source="manual"))
    t.join()

    nombres = {e["name"] for e in manager._all_entries()}
    assert nombres == {"Detectada", "Manual"}


# --------------------------------------------------------------------
# Identidad de las entradas
# --------------------------------------------------------------------

def test_id_de_shortcut_es_estable_ante_variaciones_del_path():
    """Si el id cambiara por una diferencia de formato en la ruta, se
    perderia toda la personalizacion guardada contra el id anterior
    (imagen de fondo, favorita, oculta).

    Los paths se arman con os.sep en vez de backslashes literales: en
    Windows es lo mismo, pero fuera de Windows os.path.normpath no trata
    '\\' como separador y el test comprobaria otra cosa. La app solo
    corre en Windows; esto es para que el test siga siendo valido en
    cualquier maquina de desarrollo o CI."""
    s = os.sep
    base = f"C:{s}Program Files{s}App{s}app.exe"
    con_rodeo = f"C:{s}Program Files{s}Other{s}..{s}App{s}app.exe"
    en_minuscula = base.lower()

    assert shortcut_scanner._make_id(base) == shortcut_scanner._make_id(con_rodeo)
    assert shortcut_scanner._make_id(base) == shortcut_scanner._make_id(en_minuscula)


# --------------------------------------------------------------------
# Categorias (v2)
# --------------------------------------------------------------------

def _detectadas(monkeypatch, *entries):
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [dict(e) for e in entries])


def _find(manager, eid):
    return next(e for e in manager._all_entries() if e["id"] == eid)


def test_refresh_preserva_las_favoritas(manager, monkeypatch):
    """Bug de la v1 encontrado al armar las categorias: refresh() solo
    copiaba 'hidden' y 'hover_background' de la version anterior de una
    entrada detectada, asi que las favoritas se perdian en CADA arranque
    (mismo tipo de bug que la imagen de fondo)."""
    _detectadas(monkeypatch, _entry("s1", "App"))
    manager.refresh()
    manager.set_favorite("s1", True)

    manager.refresh()

    assert manager.is_favorite("s1")


def test_app_nueva_detectada_cae_en_la_categoria_por_defecto(manager, monkeypatch):
    _detectadas(monkeypatch, _entry("s1", "App"))
    manager.refresh()
    assert manager.category_of("s1") == launcher_manager.DEFAULT_GROUP_ID


def test_refresh_respeta_la_categoria_de_cada_app(manager, monkeypatch):
    """refresh() corre en cada arranque: si volcara todo al primer grupo
    como en la v1, cualquier categorizacion se desharia sola."""
    _detectadas(monkeypatch, _entry("s1", "Juego"), _entry("s2", "Editor"))
    manager.refresh()
    manager.add_manual_entry(_entry("m1", "Manual", source="manual"))
    juegos = manager.create_category("Juegos")
    manager.move_entry_to_category("s1", juegos)
    manager.move_entry_to_category("m1", juegos)

    manager.refresh()  # arranque siguiente

    assert manager.category_of("s1") == juegos
    assert manager.category_of("m1") == juegos
    assert manager.category_of("s2") == launcher_manager.DEFAULT_GROUP_ID


def test_app_que_ya_no_se_detecta_desaparece_de_su_categoria(manager, monkeypatch):
    _detectadas(monkeypatch, _entry("s1", "App"))
    manager.refresh()
    cat = manager.create_category("Trabajo")
    manager.move_entry_to_category("s1", cat)

    _detectadas(monkeypatch)  # desinstalada
    manager.refresh()

    assert not any(e["id"] == "s1" for e in manager._all_entries())


def test_categoria_vacia_sobrevive_al_refresh(manager, monkeypatch):
    _detectadas(monkeypatch, _entry("s1", "App"))
    cat = manager.create_category("Vacia")
    manager.refresh()
    assert any(c["group_id"] == cat for c in manager.categories())


def test_mover_a_categoria_persiste_en_disco(manager, tmp_path):
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    cat = manager.create_category("Trabajo")
    assert manager.move_entry_to_category("m1", cat) is True

    otro = launcher_manager.LauncherManager(
        config_path=str(tmp_path / "launchers.json"), cache_dir=str(tmp_path / "cache")
    )
    assert otro.category_of("m1") == cat
    assert [c["title"] for c in otro.categories()] == ["Programas", "Trabajo"]


def test_mover_a_categoria_inexistente_o_app_inexistente(manager):
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    assert manager.move_entry_to_category("m1", "no-existe") is False
    assert manager.move_entry_to_category("no-existe", launcher_manager.DEFAULT_GROUP_ID) is False
    assert manager.category_of("m1") == launcher_manager.DEFAULT_GROUP_ID


def test_eliminar_categoria_devuelve_sus_apps_al_defecto(manager):
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    cat = manager.create_category("Temporal")
    manager.move_entry_to_category("m1", cat)

    assert manager.delete_category(cat) is True

    assert manager.category_of("m1") == launcher_manager.DEFAULT_GROUP_ID
    assert [c["group_id"] for c in manager.categories()] == [launcher_manager.DEFAULT_GROUP_ID]


def test_la_categoria_por_defecto_no_se_puede_eliminar(manager):
    assert manager.delete_category(launcher_manager.DEFAULT_GROUP_ID) is False
    assert manager.delete_category("no-existe") is False
    assert len(manager.categories()) == 1


def test_validacion_de_nombres_de_categoria(manager):
    manager.create_category("Juegos")
    assert manager.check_category_title("   ")
    assert manager.check_category_title("x" * (launcher_manager.MAX_CATEGORY_TITLE_LEN + 1))
    assert manager.check_category_title("  juegos ")  # repetido, sin distinguir mayusculas
    assert manager.check_category_title("Programas")   # tambien choca con la por defecto
    assert manager.check_category_title("Otra") == ""
    with pytest.raises(ValueError):
        manager.create_category("JUEGOS")
    assert len(manager.categories()) == 2  # la invalida no dejo nada a medias


def test_renombrar_categoria(manager):
    cat = manager.create_category("Juegos")
    # Su propio nombre actual no cuenta como repetido (cambiar solo mayusculas).
    assert manager.rename_category(cat, "JUEGOS") is True
    assert manager.categories()[1]["title"] == "JUEGOS"
    assert manager.rename_category("no-existe", "X") is False
    with pytest.raises(ValueError):
        manager.rename_category(cat, "Programas")
    assert manager.categories()[1]["title"] == "JUEGOS"


def test_reordenar_categorias(manager):
    a = manager.create_category("A")
    b = manager.create_category("B")
    assert manager.move_category(b, -1) is True
    assert [c["group_id"] for c in manager.categories()] == [launcher_manager.DEFAULT_GROUP_ID, b, a]
    assert manager.move_category(launcher_manager.DEFAULT_GROUP_ID, -1) is False  # ya esta arriba
    assert manager.move_category(a, +1) is False                                   # ya esta abajo


def test_reagregar_app_manual_en_otra_categoria_no_se_duplica(manager):
    cat = manager.create_category("Trabajo")
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    manager.set_favorite("m1", True)

    manager.add_manual_entry(_entry("m1", "X", source="manual"), group_id=cat)

    assert sum(1 for e in manager._all_entries() if e["id"] == "m1") == 1
    assert manager.category_of("m1") == cat
    assert manager.is_favorite("m1")


def test_reagregar_sin_categoria_conserva_la_que_tenia(manager):
    cat = manager.create_category("Trabajo")
    manager.add_manual_entry(_entry("m1", "X", source="manual"), group_id=cat)
    manager.add_manual_entry(_entry("m1", "X", source="manual"))
    assert manager.category_of("m1") == cat


def test_agregar_a_categoria_inexistente_no_crea_grupos_fantasma(manager):
    manager.add_manual_entry(_entry("m1", "X", source="manual"), group_id="borrada")
    assert manager.category_of("m1") == launcher_manager.DEFAULT_GROUP_ID
    assert len(manager.categories()) == 1


def test_visible_groups_ordena_cada_categoria_por_separado(manager):
    cat = manager.create_category("Trabajo")
    manager.add_manual_entry(_entry("m1", "Zeta", source="manual"))
    manager.add_manual_entry(_entry("m2", "Beta", source="manual"))
    manager.add_manual_entry(_entry("m3", "Alfa", source="manual"))
    manager.move_entry_to_category("m3", cat)
    manager.set_favorite("m1", True)

    grupos = manager.visible_groups("favorites_first")

    assert [e["name"] for e in grupos[0]["launchers"]] == ["Zeta", "Beta"]
    assert [e["name"] for e in grupos[1]["launchers"]] == ["Alfa"]


def test_categorias_cuenta_solo_las_visibles(manager):
    manager.add_manual_entry(_entry("m1", "A", source="manual"))
    manager.add_manual_entry(_entry("m2", "B", source="manual"))
    manager.hide_entry("m2")
    assert manager.categories()[0]["count"] == 1


def test_launchers_json_de_la_v1_sigue_siendo_valido(tmp_path):
    """Un archivo con un unico 'Group1' (el formato de la v1) se carga
    tal cual, sin migrar nada."""
    cp = tmp_path / "launchers.json"
    cp.write_text(json.dumps({"groups": [{
        "group_id": "Group1", "title": "Programas",
        "launchers": [_entry("s1", "App", favorite=True)],
    }]}), encoding="utf-8")
    m = launcher_manager.LauncherManager(config_path=str(cp), cache_dir=str(tmp_path / "c"))
    assert [c["title"] for c in m.categories()] == ["Programas"]
    assert m.is_favorite("s1")


def test_json_con_forma_rara_se_normaliza(tmp_path):
    """JSON valido pero con la estructura rota (editado a mano, o
    dañado de una forma que no lo hace invalido) no debe reventar mas
    adelante ni duplicar apps."""
    cp = tmp_path / "launchers.json"
    cp.write_text(json.dumps({"groups": [
        {"title": "Sin id", "launchers": [_entry("a", "A"), "basura", {"name": "sin id"}]},
        {"group_id": "otro", "launchers": [_entry("a", "A repetida"), _entry("b", "B")]},
        "no soy un grupo",
    ]}), encoding="utf-8")
    m = launcher_manager.LauncherManager(config_path=str(cp), cache_dir=str(tmp_path / "c"))

    ids = [e["id"] for e in m._all_entries()]
    assert sorted(ids) == ["a", "b"]                       # sin duplicados ni basura
    assert launcher_manager.DEFAULT_GROUP_ID in [c["group_id"] for c in m.categories()]
    assert all(c["title"] for c in m.categories())         # ningun grupo sin titulo
    assert len({c["group_id"] for c in m.categories()}) == len(m.categories())


def test_json_con_raiz_no_objeto_se_trata_como_corrupto(tmp_path):
    cp = tmp_path / "launchers.json"
    cp.write_text("[1, 2, 3]", encoding="utf-8")
    m = launcher_manager.LauncherManager(config_path=str(cp), cache_dir=str(tmp_path / "c"))
    assert [c["group_id"] for c in m.categories()] == [launcher_manager.DEFAULT_GROUP_ID]
    assert (tmp_path / "launchers.json.corrupt").exists()


def test_mover_de_categoria_y_refresh_concurrentes_no_se_pisan(manager, monkeypatch):
    """Mismo escenario que la carrera refresh/add_manual, pero con el
    usuario recategorizando una app mientras el escaneo esta corriendo."""
    _detectadas(monkeypatch, _entry("s1", "Detectada"))
    manager.refresh()
    cat = manager.create_category("Trabajo")

    def scan_lento():
        time.sleep(0.2)
        return [_entry("s1", "Detectada")]
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", scan_lento)

    t = threading.Thread(target=manager.refresh)
    t.start()
    time.sleep(0.05)
    manager.move_entry_to_category("s1", cat)   # queda esperando el lock del merge
    t.join()

    assert manager.category_of("s1") == cat
    assert sum(1 for e in manager._all_entries() if e["id"] == "s1") == 1


# --------------------------------------------------------------------
# Categorizacion automatica (core/auto_categories.py)
# --------------------------------------------------------------------

def _steam(appid, name):
    return {
        "id": f"steam_{appid}", "name": name, "type": "steam",
        "target": f"steam://rungameid/{appid}", "icon": "auto", "source": "auto",
        "close_after_launch": True,
    }


def _uwp(uid, name):
    return {
        "id": f"uwp_{uid}", "name": name, "type": "uwp",
        "target": f"shell:AppsFolder\\{uid}", "icon": "auto", "source": "auto",
        "close_after_launch": True,
    }


def _detect(monkeypatch, steam=(), shortcuts=(), uwp=()):
    monkeypatch.setattr("core.steam_detector.scan_steam_library", lambda *a, **k: [dict(e) for e in steam])
    monkeypatch.setattr("core.steam_detector.get_steam_path", lambda: "")
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [dict(e) for e in shortcuts])
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [dict(e) for e in uwp])


def _title_of(manager, eid):
    gid = manager.category_of(eid)
    return next(c["title"] for c in manager.categories() if c["group_id"] == gid)


def test_juegos_de_steam_van_solos_a_la_categoria_juegos(manager, monkeypatch):
    _detect(monkeypatch, steam=[_steam(730, "CS2")], shortcuts=[_entry("s1", "Editor")])
    manager.refresh()
    assert _title_of(manager, "steam_730") == "Juegos"
    assert manager.category_of("s1") == launcher_manager.DEFAULT_GROUP_ID


def test_la_categoria_juegos_se_crea_solo_si_hace_falta(manager, monkeypatch):
    _detect(monkeypatch, shortcuts=[_entry("s1", "Editor")])
    manager.refresh()
    assert [c["title"] for c in manager.categories()] == ["Programas"]


def test_una_instalacion_anterior_se_categoriza_sola(tmp_path, monkeypatch):
    """launchers.json de antes de las reglas: los juegos ya estan
    guardados en la categoria por defecto. El primer refresh() los
    acomoda sin que el usuario haga nada."""
    cp = tmp_path / "launchers.json"
    cp.write_text(json.dumps({"groups": [{
        "group_id": "Group1", "title": "Programas",
        "launchers": [_steam(730, "CS2"), _entry("s1", "Editor")],
    }]}), encoding="utf-8")
    _detect(monkeypatch, steam=[_steam(730, "CS2")], shortcuts=[_entry("s1", "Editor")])
    m = launcher_manager.LauncherManager(config_path=str(cp), cache_dir=str(tmp_path / "c"))

    m.refresh()

    assert _title_of(m, "steam_730") == "Juegos"
    assert m.category_of("s1") == launcher_manager.DEFAULT_GROUP_ID


def test_lo_que_el_usuario_movio_a_mano_no_lo_toca_la_regla(manager, monkeypatch):
    _detect(monkeypatch, steam=[_steam(1, "A"), _steam(2, "B")])
    manager.refresh()
    propia = manager.create_category("Favoritos")
    manager.move_entry_to_category("steam_1", propia)                        # a otra categoria
    manager.move_entry_to_category("steam_2", launcher_manager.DEFAULT_GROUP_ID)  # de vuelta a la por defecto

    manager.refresh()   # arranque siguiente
    manager.refresh()

    assert manager.category_of("steam_1") == propia
    assert manager.category_of("steam_2") == launcher_manager.DEFAULT_GROUP_ID


def test_renombrar_juegos_no_rompe_la_regla(manager, monkeypatch):
    _detect(monkeypatch, steam=[_steam(1, "A")])
    manager.refresh()
    gid = manager.category_of("steam_1")
    manager.rename_category(gid, "Videojuegos")

    _detect(monkeypatch, steam=[_steam(1, "A"), _steam(2, "B")])
    manager.refresh()

    assert manager.category_of("steam_2") == gid          # misma categoria, ya renombrada
    assert [c["title"] for c in manager.categories()] == ["Programas", "Videojuegos"]


def test_eliminar_juegos_no_se_vuelve_a_crear_sola(manager, monkeypatch):
    _detect(monkeypatch, steam=[_steam(1, "A")])
    manager.refresh()
    manager.delete_category(manager.category_of("steam_1"))
    assert manager.category_of("steam_1") == launcher_manager.DEFAULT_GROUP_ID

    _detect(monkeypatch, steam=[_steam(1, "A"), _steam(2, "B")])
    manager.refresh()

    assert [c["title"] for c in manager.categories()] == ["Programas"]
    assert manager.category_of("steam_2") == launcher_manager.DEFAULT_GROUP_ID


def test_recrear_a_mano_una_categoria_eliminada_la_reactiva(manager, monkeypatch):
    _detect(monkeypatch, steam=[_steam(1, "A")])
    manager.refresh()
    manager.delete_category(manager.category_of("steam_1"))

    manager.create_category("Juegos")
    manager.refresh()

    assert _title_of(manager, "steam_1") == "Juegos"


def test_si_ya_existe_una_categoria_juegos_se_usa_esa(manager, monkeypatch):
    """Una categoria 'Juegos' creada a mano se ADOPTA: crear otra con el
    mismo titulo dejaria dos categorias identicas."""
    propia = manager.create_category("juegos")
    _detect(monkeypatch, steam=[_steam(1, "A")])

    manager.refresh()

    assert manager.category_of("steam_1") == propia
    assert len(manager.categories()) == 2


def test_las_apps_manuales_nunca_se_categorizan_solas(manager, monkeypatch):
    _detect(monkeypatch)
    manager.add_manual_entry(_entry("m1", "Mi juego", source="manual",
                                    target="C:\\Program Files\\Epic Games\\X\\x.exe"))
    manager.refresh()
    assert manager.category_of("m1") == launcher_manager.DEFAULT_GROUP_ID


def test_launchers_y_juegos_de_otras_tiendas_por_ruta(manager, monkeypatch):
    def sc(eid, target):
        return _entry(eid, eid, target=target)
    _detect(monkeypatch, shortcuts=[
        sc("steam_client", "C:\\Program Files (x86)\\Steam\\steam.exe"),
        sc("epic", "C:\\Program Files (x86)\\Epic Games\\Launcher\\Portal\\Binaries\\Win32\\EpicGamesLauncher.exe"),
        sc("gog", "D:\\GOG Games\\Witcher 3\\witcher3.exe"),
        sc("juego_steam", "D:\\SteamLibrary\\steamapps\\common\\Hades\\Hades.exe"),
        sc("code", "C:\\Users\\yo\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"),
        sc("nada", "C:\\Program Files\\Games Workshop\\tool.exe"),   # 'games' suelto no alcanza
    ])
    manager.refresh()
    titles = {eid: _title_of(manager, eid) for eid in
              ("steam_client", "epic", "gog", "juego_steam", "code", "nada")}
    assert titles == {
        "steam_client": "Juegos", "epic": "Juegos", "gog": "Juegos", "juego_steam": "Juegos",
        "code": "Programas", "nada": "Programas",
    }


def test_regla_de_microsoft_store_viene_apagada_y_se_puede_activar(manager, monkeypatch):
    _detect(monkeypatch, uwp=[_uwp("calc", "Calculadora")])
    manager.refresh()
    assert manager.category_of("uwp_calc") == launcher_manager.DEFAULT_GROUP_ID

    manager.refresh(auto_rules=["games", "store"])
    assert _title_of(manager, "uwp_calc") == "Microsoft Store"


def test_sin_reglas_activas_no_se_mueve_nada(manager, monkeypatch):
    _detect(monkeypatch, steam=[_steam(1, "A")])
    manager.refresh(auto_rules=[])
    assert manager.category_of("steam_1") == launcher_manager.DEFAULT_GROUP_ID


def test_apply_auto_categories_actua_sin_reescanear(manager, monkeypatch):
    """Lo que usa Configuracion al guardar: activar una regla surte
    efecto al instante."""
    _detect(monkeypatch, steam=[_steam(1, "A")], uwp=[_uwp("calc", "Calc")])
    manager.refresh()   # 'store' apagada: calc queda en la por defecto
    assert manager.apply_auto_categories(["games", "store"]) == 1
    assert _title_of(manager, "uwp_calc") == "Microsoft Store"
    assert manager.apply_auto_categories(["games", "store"]) == 0   # idempotente


def test_la_categorizacion_automatica_persiste_en_disco(manager, monkeypatch, tmp_path):
    _detect(monkeypatch, steam=[_steam(1, "A")])
    manager.refresh()
    otro = launcher_manager.LauncherManager(
        config_path=str(tmp_path / "launchers.json"), cache_dir=str(tmp_path / "cache")
    )
    assert _title_of(otro, "steam_1") == "Juegos"


def test_dismissed_auto_rules_con_basura_se_normaliza(tmp_path):
    cp = tmp_path / "launchers.json"
    cp.write_text(json.dumps({"groups": [], "dismissed_auto_rules": ["games", 5, None]}),
                  encoding="utf-8")
    m = launcher_manager.LauncherManager(config_path=str(cp), cache_dir=str(tmp_path / "c"))
    assert m.data["dismissed_auto_rules"] == ["games"]


def test_las_reglas_activas_salen_de_settings():
    from core import auto_categories
    assert auto_categories.enabled_from_settings({}) == {"games"}
    assert auto_categories.enabled_from_settings({"auto_categories": {"games": False, "store": True}}) == {"store"}
    # settings.json de antes de que existiera la clave: defaults de config_manager
    assert auto_categories.enabled_from_settings(config_manager.DEFAULT_SETTINGS) == {"games"}


# --------------------------------------------------------------------
# is_favorite()/launch() deben esperar el lock, no leer self.data sin el
# --------------------------------------------------------------------
# A diferencia de categories()/visible_groups()/etc., estos dos metodos
# leian self.data sin tomar manager._lock -- una condicion de carrera
# real contra refresh() corriendo en su propio QThread (ver
# ui/main_window.py, start_background_scan). Se prueba de forma
# deterministica en vez de con timings/sleeps esperando una carrera:
# se toma el lock a mano en el hilo principal, se arranca un hilo que
# llama al metodo, y se verifica que ese hilo queda bloqueado mientras
# el lock sigue tomado, y que termina apenas se libera.

def test_is_favorite_espera_el_lock_en_vez_de_leer_sin_el(manager):
    manager.add_manual_entry(_entry("m1", "X", source="manual", favorite=True))
    resultado = {}
    manager._lock.acquire()
    try:
        t = threading.Thread(target=lambda: resultado.update(
            listo=True, favorito=manager.is_favorite("m1")))
        t.start()
        time.sleep(0.15)
        assert "listo" not in resultado
    finally:
        manager._lock.release()
    t.join(timeout=1)
    assert resultado == {"listo": True, "favorito": True}


def test_launch_espera_el_lock_para_buscar_la_entrada(manager, monkeypatch):
    monkeypatch.setattr("os.startfile", lambda *a, **k: None, raising=False)
    manager.add_manual_entry(_entry("m1", "X", source="manual", target="C:\\x.exe"))
    resultado = {}
    manager._lock.acquire()
    try:
        t = threading.Thread(target=lambda: resultado.update(
            listo=True, cierra=manager.launch("m1")))
        t.start()
        time.sleep(0.15)
        assert "listo" not in resultado
    finally:
        manager._lock.release()
    t.join(timeout=1)
    assert resultado["listo"] is True


# --------------------------------------------------------------------
# scan_uwp_apps() debe decodificar UTF-16, no asumir la codificacion
# ANSI/OEM del sistema
# --------------------------------------------------------------------
# PowerShell, con su salida redirigida (como hace subprocess.run), no
# necesariamente usa la misma codificacion que locale.getpreferredencoding()
# asumiria con text=True -- un nombre de app con tildes, enies, o
# cualquier caracter fuera de ASCII llegaba roto/con '?'. El fix fuerza
# UTF-16 de los dos lados (ver [Console]::OutputEncoding en _PS_SCRIPT,
# core/uwp_detector.py) y se prueba aca simulando los bytes crudos que
# realmente devolveria powershell.exe (no un str ya decodificado).

class _FakeCompletedProcess:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = b""


def test_scan_uwp_apps_decodifica_nombres_con_tildes_y_enies(monkeypatch):
    payload = [
        {
            "Name": "Música y vídeos",
            "ResolvedName": "Música y vídeos",
            "AppID": "Contoso.MusicApp_8wekyb3d8bbwe!App",
            "FamilyName": "Contoso.MusicApp_8wekyb3d8bbwe",
            "InstallLocation": r"C:\Program Files\WindowsApps\Contoso.MusicApp",
        },
        {
            "Name": "Configuración",
            "ResolvedName": "Configuración",
            "AppID": "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel",
            "FamilyName": "windows.immersivecontrolpanel_cw5n1h2txyewy",
            "InstallLocation": r"C:\Windows\ImmersiveControlPanel",
        },
    ]
    # Bytes crudos en UTF-16LE, sin BOM -- exactamente lo que escribe
    # powershell.exe en stdout con [Console]::OutputEncoding = Unicode.
    raw_bytes = json.dumps(payload).encode("utf-16-le")

    def _fake_run(*a, **k):
        return _FakeCompletedProcess(raw_bytes)

    monkeypatch.setattr("core.uwp_detector.subprocess.run", _fake_run)
    entries = uwp_detector.scan_uwp_apps()
    names = {e["name"] for e in entries}
    assert "Música y vídeos" in names
    assert "Configuración" in names


# ---------------------------------------------------------------------
# Datos del usuario separados del codigo (core/paths.py)
# ---------------------------------------------------------------------

def _paths_apuntando_a(monkeypatch, tmp_path):
    """core.paths con una carpeta de datos nueva y una 'vieja' (la que
    estaba junto al codigo) distintas, como en Windows con %APPDATA%."""
    import core.paths as paths
    legacy = tmp_path / "proyecto" / "config"
    data = tmp_path / "appdata" / "config"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(paths, "LEGACY_CONFIG_DIR", str(legacy))
    monkeypatch.setattr(paths, "CONFIG_DIR", str(data))
    return paths, legacy, data


def test_migracion_copia_los_datos_viejos_una_sola_vez(monkeypatch, tmp_path):
    paths, legacy, data = _paths_apuntando_a(monkeypatch, tmp_path)
    (legacy / "launchers.json").write_text('{"groups": []}', encoding="utf-8")
    (legacy / "settings.json").write_text('{"window": {}}', encoding="utf-8")

    assert sorted(paths.migrate_legacy_data()) == ["launchers.json", "settings.json"]
    assert (data / "launchers.json").read_text(encoding="utf-8") == '{"groups": []}'
    # Copia, no mueve: la carpeta vieja queda como respaldo.
    assert (legacy / "launchers.json").exists()
    # Segunda vez: no hay nada que copiar.
    assert paths.migrate_legacy_data() == []


def test_migracion_nunca_pisa_datos_que_ya_estan_en_la_carpeta_nueva(monkeypatch, tmp_path):
    paths, legacy, data = _paths_apuntando_a(monkeypatch, tmp_path)
    data.mkdir(parents=True)
    (data / "launchers.json").write_text('{"nuevo": true}', encoding="utf-8")
    (legacy / "launchers.json").write_text('{"viejo": true}', encoding="utf-8")

    paths.migrate_legacy_data()
    assert (data / "launchers.json").read_text(encoding="utf-8") == '{"nuevo": true}'


def test_migracion_sin_carpeta_vieja_no_falla(monkeypatch, tmp_path):
    import core.paths as paths
    monkeypatch.setattr(paths, "LEGACY_CONFIG_DIR", str(tmp_path / "no_existe"))
    monkeypatch.setattr(paths, "CONFIG_DIR", str(tmp_path / "datos"))
    assert paths.migrate_legacy_data() == []


def test_reemplazar_la_carpeta_del_proyecto_no_pierde_el_fondo(monkeypatch, tmp_path):
    """El escenario real del bug: se asigna una imagen, y despues la
    carpeta del proyecto se reemplaza por una copia vieja (con su propio
    config/launchers.json). Con los datos fuera del proyecto, el fondo
    sobrevive."""
    paths, legacy, data = _paths_apuntando_a(monkeypatch, tmp_path)
    entry = {"id": "steam_1", "name": "Juego", "type": "steam", "source": "auto"}
    doc = {"groups": [{"group_id": "Group1", "title": "Programas", "launchers": [entry]}]}
    (legacy / "launchers.json").write_text(json.dumps(doc), encoding="utf-8")
    paths.migrate_legacy_data()

    path = str(data / "launchers.json")
    launcher_manager.LauncherManager(config_path=path, cache_dir=str(tmp_path / "c")).set_hover_background("steam_1", "C:/img.jpg")

    # "Actualizar el codigo": la copia vieja del proyecto pisa su config/
    (legacy / "launchers.json").write_text(json.dumps(doc), encoding="utf-8")
    paths.migrate_legacy_data()

    reloaded = launcher_manager.LauncherManager(config_path=path, cache_dir=str(tmp_path / "c"))
    assert reloaded._count_with_bg() == 1
