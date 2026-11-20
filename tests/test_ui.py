"""
test_ui.py
------------
Tests de la capa ui/ en modo offscreen (sin ventana real): tarjetas,
pool virtualizado, modos de lista, busqueda y teclado, avisos, panel de
Configuracion y cierre ordenado.

Se saltean solos si PySide6 no esta instalado, asi `pytest tests/` sigue
sirviendo en una maquina que solo quiera probar core/.

    python -m pytest tests/ -v
"""

import copy
import json
import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget  # noqa: E402

from core import config_manager, launcher_manager  # noqa: E402
from ui.launcher_card import LauncherCard  # noqa: E402
from ui.virtual_card_list import VirtualCardList  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _spin(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _manager(tmp_path, n):
    entries = [
        {"id": f"e{i}", "name": f"App {i:03d}", "type": "shortcut", "target": f"/x{i}",
         "icon": "auto", "source": "manual"}
        for i in range(n)
    ]
    cfg = tmp_path / "launchers.json"
    cfg.write_text(json.dumps(
        {"groups": [{"group_id": "Group1", "title": "Programas", "launchers": entries}]}
    ), encoding="utf-8")
    return launcher_manager.LauncherManager(
        config_path=str(cfg), cache_dir=str(tmp_path / "cache")
    )


def _window(qapp, manager):
    from ui.main_window import MainWindow
    win = MainWindow(manager, copy.deepcopy(config_manager.DEFAULT_SETTINGS))
    win.show()
    _spin(150)
    return win


def _card_factory():
    return LauncherCard({"id": "__pool__", "name": "", "icon": "auto", "target": ""},
                        base_height=50, expand_px=34)


def _header_factory():
    label = QLabel()
    label.setFixedHeight(20)
    return label


def _groups(*sizes):
    return [
        {"title": f"Cat{gi}", "launchers": [
            {"id": f"g{gi}e{i}", "name": f"G{gi} App {i}", "icon": "auto", "target": ""}
            for i in range(size)
        ]}
        for gi, size in enumerate(sizes)
    ]


# --------------------------------------------------------------------
# Tooltip de la tarjeta: el del nombre truncado no debe tapar el de la
# ruta del programa (ver _update_name_elision en ui/launcher_card.py)
# --------------------------------------------------------------------

def test_tooltip_de_la_tarjeta_no_tapa_la_ruta_cuando_el_nombre_se_trunca(qapp):
    entry = {
        "id": "x1",
        "name": "Un Nombre De Programa Realmente Larguisimo Que No Entra",
        "icon": "auto",
        "target": "C:\\Program Files\\Ejemplo\\programa.exe",
    }
    card = LauncherCard(entry, base_height=50, expand_px=34, show_tooltip=True)
    card.resize(160, 50)
    card._update_name_elision()

    assert card._name_label.text() != card._full_name   # se trunco de verdad
    tooltip = card._name_label.toolTip()
    assert card._full_name in tooltip
    assert entry["target"] in tooltip


def test_tooltip_del_nombre_sin_la_opcion_de_ruta_activada(qapp):
    entry = {
        "id": "x1",
        "name": "Un Nombre De Programa Realmente Larguisimo Que No Entra",
        "icon": "auto",
        "target": "C:\\Program Files\\Ejemplo\\programa.exe",
    }
    card = LauncherCard(entry, base_height=50, expand_px=34, show_tooltip=False)
    card.resize(160, 50)
    card._update_name_elision()

    assert card._name_label.text() != card._full_name
    tooltip = card._name_label.toolTip()
    assert tooltip == card._full_name
    assert entry["target"] not in tooltip


# --------------------------------------------------------------------
# Pool virtualizado
# --------------------------------------------------------------------

def test_las_tarjetas_del_pool_toman_el_ancho_del_contenedor(qapp):
    """Bug de la v1: las tarjetas del pool nacian sin layout ni ancho y
    quedaban en 640px (el default de un widget) dentro de una ventana de
    ~340px -- el boton de expandir y los mini-botones de la derecha
    caian fuera de la ventana. Solo pasaba con 60+ apps."""
    container = QWidget()
    container.resize(340, 2000)
    container.show()   # un widget oculto no recibe eventos de resize hasta mostrarse
    vl = VirtualCardList(container, _card_factory, _header_factory)
    vl.set_groups(_groups(30), 94, 30, viewport_height=600)
    assert {c.width() for c in vl.cards if not c.isHidden()} == {340}

    container.resize(300, 2000)   # el ancho final se conoce despues de armar la lista
    _spin(20)
    assert {c.width() for c in vl.cards if not c.isHidden()} == {300}


def test_el_pool_cubre_el_viewport_con_varias_categorias(qapp):
    container = QWidget()
    container.resize(340, 100)
    vl = VirtualCardList(container, _card_factory, _header_factory)
    vl.set_groups(_groups(20, 1, 25), 94, 30, viewport_height=500)
    total_height = container.minimumHeight()
    assert total_height == 3 * 30 + 46 * 94

    for scroll in (0, 333, 1500, 2500, total_height - 500):
        vl.update_window(scroll, 500)
        placed = sorted(
            (w.y(), w.height()) for w in vl.cards + vl._header_pool if not w.isHidden()
        )
        for probe in range(scroll, scroll + 500, 20):
            assert any(y <= probe < y + h + 10 for y, h in placed), (scroll, probe)


def test_los_titulos_de_categoria_quedan_en_su_posicion(qapp):
    container = QWidget()
    container.resize(340, 100)
    vl = VirtualCardList(container, _card_factory, _header_factory)
    vl.set_groups(_groups(3, 2), 94, 30, viewport_height=2000)
    headers = {h.text(): h.y() for h in vl._header_pool if not h.isHidden()}
    assert headers == {"Cat0": 0, "Cat1": 30 + 3 * 94}


def test_titulo_de_categoria_largo_se_elide_en_la_lista_virtualizada(qapp):
    container = QWidget()
    container.resize(160, 100)
    vl = VirtualCardList(container, _card_factory, _header_factory)
    titulo_largo = "Una Categoria Con Un Nombre Realmente Larguisimo Que No Entra"
    vl.set_groups(
        [{"title": titulo_largo, "launchers": [
            {"id": "e0", "name": "App", "icon": "auto", "target": ""}
        ]}],
        94, 30, viewport_height=2000,
    )
    headers = [h for h in vl._header_pool if not h.isHidden()]
    assert len(headers) == 1
    header = headers[0]
    assert header.text() != titulo_largo   # se trunco
    assert header.toolTip() == titulo_largo


def test_el_pool_no_crece_con_la_cantidad_de_apps(qapp):
    container = QWidget()
    container.resize(340, 100)
    vl = VirtualCardList(container, _card_factory, _header_factory, overscan=6)
    vl.set_groups(_groups(400), 94, 30, viewport_height=600)
    assert len(vl.cards) < 30   # ~viewport + overscan, no 400


# --------------------------------------------------------------------
# MainWindow con categorias
# --------------------------------------------------------------------

def test_la_virtualizacion_cuenta_las_apps_de_todas_las_categorias(qapp, tmp_path):
    """En la v1 exigia un unico grupo: repartir 100 apps en categorias
    desactivaba la virtualizacion y volvia a construir 3 copias de 100
    tarjetas."""
    m = _manager(tmp_path, 80)
    a, b = m.create_category("A"), m.create_category("B")
    for i in range(0, 20): m.move_entry_to_category(f"e{i}", a)
    for i in range(20, 40): m.move_entry_to_category(f"e{i}", b)

    win = _window(qapp, m)
    assert win._virtual_list is not None
    assert win._virtual_list.entry_count == 80


def test_una_categoria_vacia_no_desactiva_la_virtualizacion(qapp, tmp_path):
    m = _manager(tmp_path, 80)
    m.create_category("Vacia")
    win = _window(qapp, m)
    assert win._virtual_list is not None


def test_una_lista_chica_no_virtualiza_y_muestra_los_titulos(qapp, tmp_path):
    m = _manager(tmp_path, 10)
    cat = m.create_category("Juegos")
    m.move_entry_to_category("e0", cat)
    m.create_category("Vacia")

    win = _window(qapp, m)

    assert win._virtual_list is None
    titles = [l.text() for l in win._copies[0].findChildren(QLabel) if l.text() in
              ("Programas", "Juegos", "Vacia")]
    assert titles == ["Programas", "Juegos"]   # la vacia no aparece


# --------------------------------------------------------------------
# _all_live_cards() no debe recorrer el arbol de widgets
# --------------------------------------------------------------------
# Antes recorria con findChildren(LauncherCard) cada vez que se la
# llamaba -- y se la llama desde el chequeo periodico de "hover
# fantasma" (QTimer de ~270ms, corre todo el tiempo que la ventana esta
# visible). Ahora usa self._live_cards, poblada por _wire_card() en
# ambas rutas (pool virtualizado y copias de siempre).

def test_all_live_cards_no_recorre_el_arbol_de_widgets(qapp, tmp_path, monkeypatch):
    llamadas = []
    original = QWidget.findChildren

    def espia(self, *a, **k):
        if a and a[0] is LauncherCard:
            llamadas.append(True)
        return original(self, *a, **k)

    monkeypatch.setattr(QWidget, "findChildren", espia)
    m = _manager(tmp_path, 12)
    win = _window(qapp, m)
    cards = win._all_live_cards()
    assert not llamadas
    # 12 apps no entran en la pantalla offscreen (800 px): scroll en
    # bucle, 3 copias reales.
    assert win._list_mode == "loop" and len(win._copies) == 3
    assert len(cards) == 12 * 3
    assert all(isinstance(c, LauncherCard) for c in cards)


def test_all_live_cards_se_reinicia_al_reconstruir_la_lista(qapp, tmp_path):
    m = _manager(tmp_path, 6)
    win = _window(qapp, m)
    antes = win._all_live_cards()   # se conservan las referencias: comparar identidad, no id()
    win._on_remove_requested("e0")
    _spin(80)
    despues = win._all_live_cards()
    assert not any(vieja is nueva for vieja in antes for nueva in despues)
    # 5 apps restantes, por la cantidad de copias que correspondan (3 si
    # la lista no entra en pantalla, 1 si entra).
    assert len(despues) == 5 * len(win._copies)


def test_titulo_de_categoria_largo_se_elide_en_la_lista_chica(qapp, tmp_path):
    m = _manager(tmp_path, 3)
    # 38 caracteres: el maximo que create_category() permite (40, ver
    # LauncherManager._title_error_unlocked) ya alcanza para desbordar
    # el ancho minimo de ventana permitido (260px, ver _width_slider en
    # ui/settings_window.py) con la tipografia de 10pt bold del titulo.
    titulo_largo = "Categoria Con Nombre Bastante Largo Ya"
    cat = m.create_category(titulo_largo)
    m.move_entry_to_category("e0", cat)

    win = _window(qapp, m)
    win.setFixedWidth(260)
    win._refresh_layout()

    labels = [l for l in win._copies[0].findChildren(QLabel) if l.toolTip() == titulo_largo]
    assert len(labels) == 1
    assert labels[0].text() != titulo_largo


def test_mover_una_app_desde_la_ventana_la_cambia_de_categoria(qapp, tmp_path):
    m = _manager(tmp_path, 5)
    cat = m.create_category("Juegos")
    win = _window(qapp, m)

    win._on_category_move_requested("e2", cat)
    _spin(80)

    assert m.category_of("e2") == cat


def test_el_menu_de_cada_tarjeta_recibe_las_categorias(qapp, tmp_path):
    m = _manager(tmp_path, 5)
    cat = m.create_category("Juegos")
    m.move_entry_to_category("e0", cat)
    win = _window(qapp, m)

    card = next(c for c in win._all_live_cards() if c.entry["id"] == "e0")
    categories, current = card.category_provider("e0")

    assert [c["title"] for c in categories] == ["Programas", "Juegos"]
    assert current == cat


# --------------------------------------------------------------------
# Configuracion -> Categorias
# --------------------------------------------------------------------

@pytest.fixture
def settings_dialog(qapp, tmp_path, monkeypatch):
    import ui.settings_window as sw
    # No tocar el settings.json real del proyecto.
    monkeypatch.setattr(sw, "load_settings", lambda *a, **k: copy.deepcopy(config_manager.DEFAULT_SETTINGS))
    monkeypatch.setattr(sw, "save_settings", lambda *a, **k: None)
    m = _manager(tmp_path, 3)
    return sw, sw.SettingsWindow(m), m


def _rows(dialog):
    return [dialog._category_list.item(i).text() for i in range(dialog._category_list.count())]


def test_configuracion_crear_renombrar_ordenar_y_eliminar(settings_dialog, monkeypatch):
    sw, dialog, m = settings_dialog

    monkeypatch.setattr(sw, "ask_category_name", lambda *a, **k: "Juegos")
    dialog._on_category_new()
    assert [c["title"] for c in m.categories()] == ["Programas", "Juegos"]
    assert dialog._category_list.currentItem().text().startswith("Juegos")   # queda seleccionada

    monkeypatch.setattr(sw, "ask_category_name", lambda *a, **k: "Videojuegos")
    dialog._on_category_rename()
    assert [c["title"] for c in m.categories()] == ["Programas", "Videojuegos"]

    dialog._on_category_move(-1)
    assert [c["title"] for c in m.categories()] == ["Videojuegos", "Programas"]

    dialog._on_category_delete()   # esta vacia: elimina sin confirmar
    assert [c["title"] for c in m.categories()] == ["Programas"]


def test_configuracion_no_deja_eliminar_la_categoria_por_defecto(settings_dialog):
    sw, dialog, m = settings_dialog
    dialog._category_list.setCurrentRow(0)
    assert not dialog._cat_delete_btn.isEnabled()
    dialog._on_category_delete()   # aunque se fuerce, no hace nada
    assert len(m.categories()) == 1


def test_configuracion_eliminar_con_apps_pide_confirmacion(settings_dialog, monkeypatch):
    sw, dialog, m = settings_dialog
    cat = m.create_category("Temporal")
    m.move_entry_to_category("e0", cat)
    dialog._reload_category_list(select_group_id=cat)

    monkeypatch.setattr(sw.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    dialog._on_category_delete()
    assert m.category_of("e0") == cat            # dijo que no: no se toco nada

    monkeypatch.setattr(sw.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog._on_category_delete()
    assert m.category_of("e0") == launcher_manager.DEFAULT_GROUP_ID


def test_configuracion_nombre_repetido_no_rompe_nada(settings_dialog, monkeypatch):
    """Si entre que el dialogo valida el nombre y se crea la categoria
    otro camino tomo ese nombre, create_category lanza ValueError: la UI
    lo muestra, no lo deja propagar dentro de un slot de Qt."""
    sw, dialog, m = settings_dialog
    avisos = []
    monkeypatch.setattr(sw.QMessageBox, "warning", staticmethod(lambda *a, **k: avisos.append(a[2])))
    monkeypatch.setattr(sw, "ask_category_name", lambda *a, **k: "Programas")
    dialog._on_category_new()
    assert avisos and len(m.categories()) == 1


def test_configuracion_las_reglas_automaticas_se_guardan_y_se_aplican(settings_dialog, monkeypatch):
    """Tildar una regla y Guardar: queda en settings["auto_categories"] y
    se aplica al instante sobre lo ya cargado (sin re-escanear)."""
    sw, dialog, m = settings_dialog
    # Una app UWP ya cargada en la categoria por defecto; la regla 'store' viene apagada.
    m.data["groups"][0]["launchers"].append(
        {"id": "uwp_calc", "name": "Calc", "type": "uwp", "target": "shell:AppsFolder\\calc",
         "icon": "auto", "source": "auto"}
    )
    assert dialog._auto_rule_checks["games"].isChecked()
    assert not dialog._auto_rule_checks["store"].isChecked()

    guardado = {}
    monkeypatch.setattr(sw, "save_settings", lambda settings, *a, **k: guardado.update(settings))
    dialog._auto_rule_checks["store"].setChecked(True)
    dialog._on_save()

    assert guardado["auto_categories"] == {"games": True, "store": True}
    assert [c["title"] for c in m.categories()] == ["Programas", "Microsoft Store"]
    assert m.category_of("uwp_calc") != launcher_manager.DEFAULT_GROUP_ID


# --------------------------------------------------------------------
# "Buscar de nuevo ahora" no debe bloquear el dialogo (ver
# _on_rescan_clicked en ui/settings_window.py)
# --------------------------------------------------------------------
# Antes llamaba a launcher_manager.refresh() directo en el hilo de UI
# -- un escaneo lento congelaba TODO el dialogo de Configuracion.
# Ahora corre en el mismo QThread en background que usa el escaneo
# automatico al iniciar. Se prueba de forma deterministica (igual que
# los tests de lock en tests/test_core.py): un detector "lento" que se
# bloquea hasta que el test lo libera, para verificar que
# _on_rescan_clicked() ya volvio (no bloqueo) mientras el escaneo sigue
# corriendo en su propio hilo.

def test_rescan_corre_en_background_y_no_bloquea_el_dialogo(settings_dialog, monkeypatch):
    sw, dialog, m = settings_dialog
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [])
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])

    empezo = threading.Event()
    seguir = threading.Event()

    def steam_lento(*a, **k):
        empezo.set()
        seguir.wait(timeout=2)
        return []

    monkeypatch.setattr("core.steam_detector.scan_steam_library", steam_lento)

    dialog._on_rescan_clicked()
    assert empezo.wait(timeout=1)   # el worker ya arranco en su propio hilo...
    # ...y sin embargo _on_rescan_clicked() ya volvio: el dialogo sigue
    # marcado como "escaneando" (no colgado) y sus controles reflejan
    # eso, no un freeze.
    assert dialog._rescan_running is True
    assert not dialog._rescan_btn.isEnabled()
    assert not dialog._save_btn.isEnabled()
    assert not dialog._cancel_btn.isEnabled()

    seguir.set()
    _spin(300)   # deja correr el QThread y procesar sus signals en el loop de eventos
    assert dialog._rescan_running is False
    assert dialog._rescan_btn.isEnabled()
    assert dialog._save_btn.isEnabled()
    assert dialog._cancel_btn.isEnabled()
    assert dialog._rescan_status.text() == "Lista actualizada."


def test_cerrar_el_dialogo_durante_un_rescan_no_lo_cierra(settings_dialog, monkeypatch):
    sw, dialog, m = settings_dialog
    monkeypatch.setattr("core.uwp_detector.scan_uwp_apps", lambda: [])
    monkeypatch.setattr("core.shortcut_scanner.scan_shortcuts", lambda: [])
    seguir = threading.Event()
    monkeypatch.setattr(
        "core.steam_detector.scan_steam_library",
        lambda *a, **k: (seguir.wait(timeout=2), [])[1],
    )
    cerrado = []
    dialog.finished.connect(lambda _code: cerrado.append(True))

    dialog._on_rescan_clicked()
    _spin(30)
    assert dialog._rescan_running is True

    dialog.reject()   # Cancelar / Escape mientras el escaneo sigue corriendo
    assert not cerrado   # reject() no hizo nada: el dialogo sigue abierto

    seguir.set()
    _spin(300)
    assert dialog._rescan_running is False

    dialog.reject()   # ahora si debe cerrar
    assert cerrado


def test_el_checkbox_de_regla_automatica_no_lleva_la_descripcion_pegada(settings_dialog):
    """El checkbox de cada regla (ver _build_categories_page) solo debe
    llevar el titulo -- QCheckBox no hace word-wrap, asi que la
    descripcion larga (90-110 caracteres segun la regla) se separo a un
    QLabel con wordWrap aparte para no quedar cortada contra el ancho
    minimo del dialogo."""
    from core import auto_categories
    sw, dialog, m = settings_dialog
    for rule in auto_categories.RULES:
        check = dialog._auto_rule_checks[rule.rule_id]
        assert check.text() == rule.title
        assert rule.description not in check.text()


# ---------------------------------------------------------------------
# Cierre ordenado (Cerrar en la bandeja, Ctrl+C)
# ---------------------------------------------------------------------

def test_shutdown_oculta_todo_y_detiene_timers(qapp, tmp_path):
    win = _window(qapp, _manager(tmp_path, 5))
    assert win.isVisible() and win._pulse_timer.isActive()

    win.shutdown()

    assert not win.isVisible()
    assert not win._tray_icon.isVisible()
    assert not win._pulse_timer.isActive()


def test_shutdown_es_idempotente(qapp, tmp_path):
    win = _window(qapp, _manager(tmp_path, 3))
    win.shutdown()
    win.shutdown()  # aboutToQuit + Cerrar pueden llamarlo las dos
    assert win._shutting_down is True


def test_shutdown_no_se_cuelga_con_un_hilo_de_fondo_ocupado(qapp, tmp_path):
    """Un escaneo a medias (PowerShell tarda segundos) no debe mantener
    cerrandose al programa: shutdown() espera un tope y sigue."""
    import time
    from PySide6.QtCore import QObject, QThread

    class _Lento(QObject):
        def run(self):
            time.sleep(1.2)

    win = _window(qapp, _manager(tmp_path, 3))
    win._SHUTDOWN_WAIT_MS = 200

    thread = QThread()
    worker = _Lento()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
    win._scan_thread = thread
    _spin(50)

    t0 = time.monotonic()
    win.shutdown()
    elapsed = time.monotonic() - t0

    assert elapsed < 0.9, f"shutdown espero demasiado ({elapsed:.2f}s)"
    assert thread.isRunning()  # se dejo de esperar, no se mato

    thread.quit()
    assert thread.wait(5000)  # limpieza del propio test


def test_shutdown_tolera_un_qthread_ya_destruido(qapp, tmp_path):
    """start_scan() deja thread.deleteLater() programado: despues de
    terminar, tocar ese objeto lanza RuntimeError. No debe romper el cierre."""
    from PySide6.QtCore import QThread
    from shiboken6 import delete

    win = _window(qapp, _manager(tmp_path, 3))
    thread = QThread()
    win._scan_thread = thread
    delete(thread)

    win.shutdown()  # no debe lanzar


def test_ctrl_c_en_la_terminal_cierra_la_aplicacion(qapp, monkeypatch):
    """Un SIGINT (Ctrl+C), enviado desde otro hilo mientras el bucle de Qt
    esta corriendo, termina pidiendo el cierre de la aplicacion. Nota: en
    Linux este test pasa incluso sin el timer de _enable_ctrl_c, asi que no
    demuestra que el timer sea necesario; en Windows, donde Python no
    recupera el control durante el bucle de Qt, ese timer es el que lo
    garantiza (practica habitual con Qt). Verifica el cableado de punta a punta."""
    import signal
    import threading
    import main as main_module

    called = []
    monkeypatch.setattr(qapp, "quit", lambda: called.append(True))
    previous = signal.getsignal(signal.SIGINT)
    try:
        main_module._enable_ctrl_c(qapp)
        threading.Timer(0.1, os.kill, args=(os.getpid(), signal.SIGINT)).start()
        _spin(900)
        assert called, "Ctrl+C no llego a pedir el cierre de la aplicacion"
    finally:
        qapp._signal_wake_timer.stop()
        signal.signal(signal.SIGINT, previous)


def test_la_bandeja_ofrece_abrir_la_carpeta_de_datos(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    import ui.main_window as mw

    win = _window(qapp, _manager(tmp_path, 3))
    textos = [a.text() for a in win._tray_menu.actions()]
    assert "Abrir carpeta de datos" in textos

    datos = tmp_path / "datos_usuario"
    abiertas = []
    monkeypatch.setattr(mw, "DATA_DIR", str(datos))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: abiertas.append(url.toLocalFile()))

    win._open_data_folder()

    assert datos.is_dir()  # se crea si todavia no existia
    assert abiertas == [str(datos)]
    win.shutdown()



# ---------------------------------------------------------------------
# Modos de lista
# ---------------------------------------------------------------------

def test_una_lista_que_entra_en_pantalla_no_se_triplica(qapp, tmp_path):
    """Con pocas apps, las 3 copias del scroll en bucle entraban todas
    en pantalla y la lista se veia repetida."""
    win = _window(qapp, _manager(tmp_path, 3))
    assert win._list_mode == "single"
    assert len(win._copies) == 1
    assert len(win._all_live_cards()) == 3
    win.shutdown()


def test_un_escaneo_sin_cambios_no_reconstruye_la_lista(qapp, tmp_path):
    m = _manager(tmp_path, 6)
    win = _window(qapp, m)
    antes = win._all_live_cards()

    m.last_refresh = {"changed": False, "added": 0, "removed": 0, "failed": []}
    win._on_scan_finished()
    _spin(50)
    despues = win._all_live_cards()
    assert len(despues) == len(antes) and all(a is b for a, b in zip(antes, despues))

    m.last_refresh = {"changed": True, "added": 2, "removed": 0, "failed": []}
    win._on_scan_finished()
    _spin(50)
    assert not any(a is b for a in antes for b in win._all_live_cards())
    assert "2 nuevas" in win._toast._label.text()
    win.shutdown()


# ---------------------------------------------------------------------
# Busqueda y teclado
# ---------------------------------------------------------------------

def _type(win, text):
    win._search_box.setText(text)
    _spin(250)   # deja vencer el debounce de la busqueda


def test_buscar_ignora_acentos_y_selecciona_el_mejor_resultado(qapp, tmp_path):
    m = _manager(tmp_path, 5)
    m.add_manual_entry({"id": "cam", "name": "Cámara", "type": "shortcut", "target": "/cam", "icon": "auto"})
    win = _window(qapp, m)

    _type(win, "camara")

    assert [e["id"] for e in win._nav_entries] == ["cam"]
    assert win._selected_id == "cam"
    assert [c.entry["id"] for c in win._all_live_cards() if c._selected] == ["cam"]
    win.shutdown()


def test_enter_abre_el_mejor_resultado_una_sola_vez(qapp, tmp_path, monkeypatch):
    abiertos = []
    monkeypatch.setattr(os, "startfile", abiertos.append, raising=False)
    win = _window(qapp, _manager(tmp_path, 20))

    _type(win, "app 007")
    win._search_box.returnPressed.emit()
    win._search_box.returnPressed.emit()   # un segundo Enter (o un doble clic) inmediato

    assert abiertos == ["/x7"]
    assert "Abriendo App 007" in win._toast._label.text()
    win.shutdown()


def test_enter_antes_de_que_venza_el_debounce_usa_el_texto_actual(qapp, tmp_path, monkeypatch):
    abiertos = []
    monkeypatch.setattr(os, "startfile", abiertos.append, raising=False)
    win = _window(qapp, _manager(tmp_path, 20))

    win._search_box.setText("app 012")
    win._search_box.returnPressed.emit()   # sin esperar

    assert abiertos == ["/x12"]
    win.shutdown()


def test_sin_resultados_muestra_un_mensaje_y_no_hay_seleccion(qapp, tmp_path):
    win = _window(qapp, _manager(tmp_path, 5))
    _type(win, "zzzz")
    assert win._list_mode == "empty" and win._selected_id is None
    assert any("Sin resultados" in label.text() for label in win._scroll_area.widget().findChildren(QLabel))
    win.shutdown()


def test_escape_limpia_la_busqueda_antes_de_ocultar(qapp, tmp_path):
    win = _window(qapp, _manager(tmp_path, 5))
    _type(win, "app")

    win._on_escape()
    _spin(50)
    assert win._search_box.text() == "" and win.isVisible()
    assert len(win._nav_entries) == 5       # volvio la lista completa, sin esperar el debounce

    win._on_escape()
    _spin(500)                               # fade-out
    assert not win.isVisible()
    win.shutdown()


def test_flechas_mueven_la_seleccion(qapp, tmp_path):
    from PySide6.QtCore import Qt

    win = _window(qapp, _manager(tmp_path, 8))
    assert win._selected_id is None

    assert win._handle_nav_key(Qt.Key.Key_Down) is True
    assert win._selected_id == "e0"
    win._handle_nav_key(Qt.Key.Key_Down)
    assert win._selected_id == "e1"
    win._handle_nav_key(Qt.Key.Key_Up)
    win._handle_nav_key(Qt.Key.Key_Up)
    assert win._selected_id == "e0"         # no pasa del principio
    assert win._handle_nav_key(Qt.Key.Key_A) is False
    assert any(c._selected and c.entry["id"] == "e0" for c in win._all_live_cards())
    win.shutdown()


def test_flecha_abajo_dentro_del_buscador(qapp, tmp_path):
    QtTest = pytest.importorskip("PySide6.QtTest")
    from PySide6.QtCore import Qt

    win = _window(qapp, _manager(tmp_path, 8))
    QtTest.QTest.keyClick(win._search_box, Qt.Key.Key_Down)
    assert win._selected_id == "e0"
    win.shutdown()


def test_buscar_en_una_lista_grande_reutiliza_el_pool(qapp, tmp_path):
    """Con el pool ya armado, cambiar los datos (buscar, marcar una
    favorita) no reconstruye nada: solo se le pasan las filas nuevas."""
    win = _window(qapp, _manager(tmp_path, 200))
    pool = win._virtual_list
    assert pool is not None
    cartas = win._all_live_cards()

    _type(win, "app 1")                      # mas de 60 resultados
    assert win._virtual_list is pool
    assert win._scroll_area.verticalScrollBar().value() == 0
    assert all(a is b for a, b in zip(cartas, win._all_live_cards()))

    win._on_favorite_toggled("e150", True)
    _spin(80)
    assert win._virtual_list is pool
    win.shutdown()


def test_el_pool_no_reasigna_las_filas_que_siguen_visibles(qapp):
    container = QWidget()
    container.resize(340, 100)
    vl = VirtualCardList(container, _card_factory, _header_factory, overscan=6)
    vl.set_groups(_groups(400), 94, 30, viewport_height=600)
    antes = {id(c): c.entry["id"] for c in vl.cards if not c.isHidden()}

    vl.update_window(94 * 3, 600)            # avanza tres filas
    despues = {id(c): c.entry["id"] for c in vl.cards if not c.isHidden()}

    conservadas = sum(1 for key, entry_id in antes.items() if despues.get(key) == entry_id)
    assert conservadas >= len(antes) - 4
    assert len(set(despues.values())) == len(despues)   # ninguna app repetida
    assert vl.row_of("g0e10") == (30 + 10 * 94, 94)
    assert vl.row_of("no_existe") is None


# ---------------------------------------------------------------------
# Respuesta a las acciones
# ---------------------------------------------------------------------

def test_quitar_una_app_se_puede_deshacer_desde_el_aviso(qapp, tmp_path):
    m = _manager(tmp_path, 6)
    win = _window(qapp, m)

    win._on_remove_requested("e2")
    _spin(80)
    assert "e2" not in [e["id"] for e in win._nav_entries]
    assert win._toast.isVisible() and win._toast._button.text() == "Deshacer"

    win._toast._button.click()
    _spin(80)
    assert "e2" in [e["id"] for e in win._nav_entries]
    assert not m.hidden_entries()
    win.shutdown()


def test_el_clic_que_termina_un_arrastre_no_abre_la_app(qapp, tmp_path, monkeypatch):
    abiertos = []
    monkeypatch.setattr(os, "startfile", abiertos.append, raising=False)
    win = _window(qapp, _manager(tmp_path, 4))

    win._drag_moved = True                   # se esta soltando el boton tras arrastrar la ventana
    win._on_card_clicked("e1")
    assert abiertos == []

    win._drag_moved = False
    win._on_card_clicked("e1")
    assert abiertos == ["/x1"]
    win.shutdown()


def test_error_al_abrir_avisa_y_deja_reintentar(qapp, tmp_path, monkeypatch):
    def falla(_path):
        raise OSError("no existe")

    monkeypatch.setattr(os, "startfile", falla, raising=False)
    win = _window(qapp, _manager(tmp_path, 4))

    win._on_card_clicked("e1")
    assert "No se pudo abrir App 001" in win._toast._label.text()
    assert win._last_launch[0] is None       # el reintento inmediato no se bloquea
    win.shutdown()


def test_elegir_imagen_de_fondo_lo_hace_la_ventana(qapp, tmp_path, monkeypatch):
    """El dialogo de archivo ya no se abre dentro del menu de la tarjeta
    (que puede destruirse mientras esta abierto)."""
    import ui.main_window as mw

    m = _manager(tmp_path, 4)
    win = _window(qapp, m)
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("C:/img/fondo.png", "")))

    card = next(c for c in win._all_live_cards() if c.entry["id"] == "e3")
    card.background_pick_requested.emit("e3")
    _spin(80)

    assert m.get_entry("e3")["hover_background"] == "C:/img/fondo.png"
    assert "Imagen de fondo asignada" in win._toast._label.text()
    win.shutdown()


def test_toast_muestra_texto_y_accion(qapp):
    from ui.toast import Toast

    parent = QWidget()
    parent.resize(380, 600)
    parent.show()
    aviso = Toast(parent)
    llamadas = []

    aviso.show_message("Hola", action_text="Deshacer", on_action=lambda: llamadas.append(True))
    assert aviso.isVisible() and aviso._label.text() == "Hola"
    assert not aviso._button.isHidden()
    assert 0 <= aviso.x() and aviso.x() + aviso.width() <= parent.width()

    aviso._button.click()
    assert llamadas == [True]

    aviso.show_message("Sin accion")
    assert aviso._button.isHidden()


# ---------------------------------------------------------------------
# Tarjeta: fondo perezoso, reducido, y seleccion
# ---------------------------------------------------------------------

def test_la_tarjeta_no_carga_su_imagen_de_fondo_al_crearse(qapp, tmp_path):
    entry = {"id": "x", "name": "X", "icon": "auto", "target": "",
             "hover_background": str(tmp_path / "no_existe.png")}
    card = LauncherCard(entry, base_height=50, expand_px=34)
    assert card._bg_loaded is False
    assert card._ensure_bg() is None and card._bg_loaded is True

    card.set_selected(True)
    assert card._selected
    card.update_entry({"id": "y", "name": "Y", "icon": "auto", "target": ""})
    assert not card._selected and card._bg_loaded is False


def test_la_imagen_de_fondo_se_guarda_reducida(qapp, tmp_path):
    from PySide6.QtGui import QImage
    import ui.launcher_card as lc

    path = str(tmp_path / "grande.png")
    image = QImage(3000, 1000, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(path)

    pix = lc._load_bg_pixmap(path)
    assert pix is not None
    assert max(pix.width(), pix.height()) == lc._BG_MAX_SIDE
    assert lc._load_bg_pixmap(path) is pix   # segunda vez: de la cache


def test_el_dialogo_de_configuracion_detiene_su_temporizador_al_cerrar(settings_dialog):
    sw, dialog, m = settings_dialog
    assert dialog._preview_timer.isActive()
    dialog.done(0)
    assert not dialog._preview_timer.isActive()
