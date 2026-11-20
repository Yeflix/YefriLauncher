"""
config_manager.py
-------------------
Carga y guarda settings.json (ventana, animacion, deteccion, reglas de
categorias, atajo). La ruta sale de core.paths (absoluta, en la carpeta
de datos del usuario).

Garantias de load_settings()
------------------------------
* Siempre devuelve TODAS las claves de DEFAULT_SETTINGS: lo que falte en
  el archivo (una version anterior) se completa con el valor por defecto.
* Un valor con el tipo equivocado (el archivo se edito a mano, o quedo
  dañado de una forma que sigue siendo JSON valido) se descarta y se usa
  el valor por defecto, en vez de reventar mas tarde en la interfaz.
* Los numeros se recortan a su rango valido.
* Un archivo corrupto se aparta como '.corrupt' y se arranca con los
  valores por defecto.
"""

import copy
import json
import os

from core.paths import SETTINGS_PATH

DEFAULT_SETTINGS = {
    "window": {
        "width": 380,
        "always_on_top": True,
        "background_alpha": 220,
        "compact_card_height": 50,
        "show_tooltips": False,
        "sort_mode": "favorites_first",
        # Ultima posicion de la ventana (None = la decide Windows).
        "x": None,
        "y": None
    },
    "animation": {
        "duration_ms": 220,
        "easing": "OutCubic",
        "hover_expand_px": 34,
        "hover_slide_px": 14,
        "hover_slide_direction": "right",
        "hover_slide_mode": "content_only",
        "arrow_side_preference": "right",
        "expand_overlay_height_px": 220,
        "speed_multiplier": 1.0
    },
    "buttons": {
        "special_buttons_placement": "outside"
    },
    "detection": {
        "auto_scan_on_launch": True,
        "scan_steam": True,
        "scan_shortcuts": True,
        "scan_uwp": True
    },
    "auto_categories": {
        "games": True,
        "store": False
    },
    "hotkey_toggle": "ctrl+alt+space"
}

# (seccion, clave) -> (minimo, maximo). Los mismos rangos que los
# controles de Configuracion.
_NUMERIC_LIMITS = {
    ("window", "width"): (260, 600),
    ("window", "background_alpha"): (80, 255),
    ("window", "compact_card_height"): (32, 80),
    ("animation", "duration_ms"): (80, 600),
    ("animation", "hover_expand_px"): (0, 80),
    ("animation", "hover_slide_px"): (0, 40),
    ("animation", "expand_overlay_height_px"): (100, 500),
    ("animation", "speed_multiplier"): (0.5, 2.0),
}

# (seccion, clave) -> valores permitidos.
_CHOICES = {
    ("window", "sort_mode"): ("favorites_first", "alphabetical", "none"),
    ("animation", "hover_slide_direction"): ("right", "left", "none"),
    ("animation", "hover_slide_mode"): ("content_only", "full_card"),
    ("animation", "arrow_side_preference"): ("right", "left"),
    ("buttons", "special_buttons_placement"): ("outside", "inside", "hidden"),
}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_kind(default, value) -> bool:
    """True si 'value' puede reemplazar a 'default' sin cambiarle el tipo."""
    if default is None:
        return value is None or (isinstance(value, int) and not isinstance(value, bool))
    if isinstance(default, bool):
        return isinstance(value, bool)
    if _is_number(default):
        return _is_number(value)
    if isinstance(default, str):
        return isinstance(value, str)
    return isinstance(value, type(default))


def _merge_with_defaults(defaults: dict, overrides: dict) -> dict:
    """Copia profunda de 'defaults' con lo de 'overrides' encima,
    recursivo para las secciones. Las claves que DEFAULT_SETTINGS no
    conoce se conservan tal cual (un archivo de una version mas nueva)."""
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if key not in merged:
            merged[key] = value
            continue
        default = merged[key]
        if isinstance(default, dict):
            if isinstance(value, dict):
                merged[key] = _merge_with_defaults(default, value)
            continue  # una seccion que no es un objeto: se ignora
        if _same_kind(default, value):
            merged[key] = value
    return merged


def _sanitize(settings: dict) -> dict:
    for (section, key), (low, high) in _NUMERIC_LIMITS.items():
        value = min(high, max(low, settings[section][key]))
        if isinstance(DEFAULT_SETTINGS[section][key], int):
            value = int(round(value))  # los controles de Qt no aceptan 380.5
        settings[section][key] = value
    for (section, key), allowed in _CHOICES.items():
        if settings[section][key] not in allowed:
            settings[section][key] = DEFAULT_SETTINGS[section][key]
    return settings


def load_settings(path=None) -> dict:
    path = path or SETTINGS_PATH
    if not os.path.exists(path):
        _try_save(DEFAULT_SETTINGS, path)
        return copy.deepcopy(DEFAULT_SETTINGS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            pass
        _try_save(DEFAULT_SETTINGS, path)
        return copy.deepcopy(DEFAULT_SETTINGS)

    if not isinstance(loaded, dict):
        loaded = {}
    return _sanitize(_merge_with_defaults(DEFAULT_SETTINGS, loaded))


def _try_save(settings: dict, path: str) -> None:
    """Crear el archivo por primera vez no debe impedir que el programa
    arranque si la carpeta no se puede escribir."""
    try:
        save_settings(settings, path)
    except OSError:
        pass


def save_settings(settings: dict, path=None) -> None:
    """Escritura atomica: a un temporal en la misma carpeta y
    os.replace() al final, para que una interrupcion nunca deje el
    archivo truncado."""
    path = path or SETTINGS_PATH
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
