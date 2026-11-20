"""
auto_categories.py
---------------------
Reglas que mandan solas una app RECIEN DETECTADA a una categoria
(ver "Categorías" en README.md). No hace I/O ni conoce launchers.json:
solo dice "esta entrada encaja en la regla X". Quien la aplica y crea la
categoria si hace falta es LauncherManager (ver _apply_auto_rules_unlocked).

Que se puede detectar de forma FIABLE
----------------------------------------
Solo lo que sale de datos que el detector ya trae, no de adivinar por el
nombre de la app:

  * el ORIGEN de la entrada: 'type' == "steam" es un juego, sin dudas;
    'type' == "uwp" viene de Microsoft Store;
  * la RUTA del ejecutable de un acceso directo: las carpetas de
    biblioteca de las tiendas de juegos (steamapps\\common, Epic Games,
    GOG, Riot...) y los ejecutables de los launchers de juegos.

Las categorias "semanticas" (navegadores, desarrollo, multimedia...)
requeririan una lista de nombres de programas que siempre va a quedar
incompleta; no se incluyen. Agregar una es agregar una AutoRule a RULES.

Windows tampoco da una categoria "Sistema": shortcut_scanner ya descarta
las herramientas de C:\\Windows antes de que lleguen aca.

Como agregar una regla
-------------------------
1. Escribir una funcion (entry: dict) -> bool.
2. Sumar un AutoRule a RULES, con un 'group_id' propio y estable (es lo
   que identifica a la categoria aunque el usuario la renombre).
Nada mas: la UI (Configuracion -> Categorias) y el resto se arman
recorriendo RULES.
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class AutoRule:
    rule_id: str            # clave en settings.json ("auto_categories") y en launchers.json
    group_id: str           # id estable de la categoria que crea la regla
    title: str              # nombre inicial (el usuario puede renombrarla)
    description: str        # una linea para el panel de Configuracion
    default_enabled: bool
    matches: Callable[[dict], bool]


def _normalized_target(entry: dict) -> str:
    """Ruta en minusculas y con '\\' como unico separador, para que la
    misma regla funcione igual con rutas de Windows y con las rutas
    'a la Unix' de los tests."""
    return (entry.get("target") or "").lower().replace("/", "\\")


# ---------- Juegos ----------

# Carpetas donde las tiendas/launchers instalan sus juegos (o a si
# mismos). Se busca como substring de la ruta normalizada.
_GAME_PATH_FRAGMENTS = (
    "\\steamapps\\common\\",
    "\\epic games\\",
    "\\gog galaxy\\",
    "\\gog games\\",
    "\\riot games\\",
    "\\ubisoft game launcher\\",
    "\\ea games\\",
    "\\origin games\\",
    "\\rockstar games\\",
    "\\battle.net\\",
    "\\blizzard entertainment\\",
    "\\xboxgames\\",
)

# Los launchers de juegos en si (no viven siempre bajo una carpeta con
# nombre reconocible: Steam esta en 'Program Files (x86)\\Steam').
_GAME_LAUNCHER_EXES = frozenset({
    "steam.exe",
    "epicgameslauncher.exe",
    "galaxyclient.exe",
    "battle.net.exe",
    "battle.net launcher.exe",
    "ubisoftconnect.exe",
    "upc.exe",
    "eadesktop.exe",
    "origin.exe",
    "riotclientservices.exe",
    "itch.exe",
})


def _is_game(entry: dict) -> bool:
    if entry.get("type") == "steam":
        return True
    if entry.get("type") != "shortcut":
        return False
    target = _normalized_target(entry)
    if not target:
        return False
    if target.rsplit("\\", 1)[-1] in _GAME_LAUNCHER_EXES:
        return True
    return any(fragment in target for fragment in _GAME_PATH_FRAGMENTS)


# ---------- Microsoft Store ----------

def _is_store_app(entry: dict) -> bool:
    return entry.get("type") == "uwp"


RULES = (
    AutoRule(
        rule_id="games",
        group_id="auto_games",
        title="Juegos",
        description="juegos de Steam y launchers/juegos de Epic, GOG, Riot, Battle.net, EA y Ubisoft",
        default_enabled=True,
        matches=_is_game,
    ),
    AutoRule(
        rule_id="store",
        group_id="auto_store",
        title="Microsoft Store",
        description="apps de Microsoft Store (calculadora, fotos, etc.), para no mezclarlas con tus programas",
        default_enabled=False,
        matches=_is_store_app,
    ),
)

DEFAULT_ENABLED = frozenset(rule.rule_id for rule in RULES if rule.default_enabled)


def rule_by_id(rule_id: str) -> Optional[AutoRule]:
    return next((r for r in RULES if r.rule_id == rule_id), None)


def rule_for_group(group_id: str, title: str) -> Optional[AutoRule]:
    """La regla a la que pertenece una categoria, por su id estable o
    (si el usuario la creo a mano con el mismo nombre) por su titulo."""
    folded = (title or "").strip().casefold()
    for rule in RULES:
        if group_id == rule.group_id or folded == rule.title.casefold():
            return rule
    return None


def enabled_from_settings(settings: dict) -> frozenset:
    """Ids de las reglas activas segun settings["auto_categories"] (un
    {rule_id: bool}); lo que falte usa el valor por defecto de la regla."""
    chosen = settings.get("auto_categories") or {}
    return frozenset(
        rule.rule_id for rule in RULES
        if bool(chosen.get(rule.rule_id, rule.default_enabled))
    )
