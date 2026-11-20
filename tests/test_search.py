"""
test_search.py
----------------
Motor de busqueda (core/search.py). Logica pura: corre en cualquier
sistema.
"""

from core import search


def _e(name, target="", **extra):
    return {"id": name, "name": name, "target": target, **extra}


APPS = [
    _e("Cámara"),
    _e("Calculadora"),
    _e("Visual Studio Code", r"C:\Program Files\Microsoft VS Code\Code.exe"),
    _e("Visual Studio 2022", r"C:\VS\devenv.exe"),
    _e("Word", r"C:\Office\WINWORD.EXE"),
    _e("Adobe Photoshop 2024", r"C:\Adobe\Photoshop.exe"),
    _e("Música y vídeos"),
    _e("Steam"),
    _e("Counter-Strike 2"),
]


def _names(query, apps=APPS):
    return [e["name"] for e in search.search(apps, query)]


def test_ignora_acentos_y_mayusculas():
    assert _names("camara") == ["Cámara"]
    assert _names("CÁMARA") == ["Cámara"]
    assert _names("musica") == ["Música y vídeos"]


def test_busqueda_vacia_o_solo_simbolos_no_devuelve_nada():
    assert _names("") == []
    assert _names("   ") == []
    assert _names("!!!") == []
    assert search.tokenize("  -- ") == []


def test_todas_las_palabras_deben_aparecer_en_cualquier_orden():
    assert _names("code visual") == ["Visual Studio Code"]
    # Mismo puntaje y mismo largo: desempata el orden alfabetico.
    assert _names("visual studio") == ["Visual Studio 2022", "Visual Studio Code"]
    assert _names("visual excel") == []


def test_el_prefijo_del_nombre_gana_a_la_coincidencia_interna():
    apps = [_e("Mi Steam Tool"), _e("Steam"), _e("Steamworks")]
    assert _names("steam", apps) == ["Steam", "Steamworks", "Mi Steam Tool"]


def test_siglas():
    assert _names("vsc")[0] == "Visual Studio Code"
    assert "Adobe Photoshop 2024" in _names("ap")


def test_nombre_del_ejecutable():
    assert _names("winword") == ["Word"]
    assert _names("devenv") == ["Visual Studio 2022"]


def test_letras_salteadas_solo_como_ultimo_recurso():
    assert _names("phtshp") == ["Adobe Photoshop 2024"]
    # Una coincidencia real siempre queda por encima de una aproximada.
    apps = [_e("Cool Reader"), _e("Calendario")]
    assert _names("cal", apps)[0] == "Calendario"


def test_las_favoritas_desempatan():
    apps = [_e("Notas A"), _e("Notas B", favorite=True)]
    assert _names("notas", apps) == ["Notas B", "Notas A"]


def test_nombre_con_guion_se_parte_en_palabras():
    assert _names("strike") == ["Counter-Strike 2"]
    assert _names("cs2") == ["Counter-Strike 2"]


def test_entradas_con_datos_raros_no_rompen():
    apps = [{"id": "x"}, {"id": "y", "name": None, "target": None}, _e("Bloc de notas")]
    assert _names("notas", apps) == ["Bloc de notas"]
