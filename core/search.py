"""
search.py
-----------
Motor de busqueda de la lista de apps. Logica pura (sin Qt ni Windows),
para poder testearla en cualquier sistema.

Que entiende
--------------
* Ignora mayusculas y acentos: "camara" encuentra "Cámara".
* Varias palabras: todas tienen que aparecer, en cualquier orden
  ("code visual" encuentra "Visual Studio Code").
* Siglas: "vsc" encuentra "Visual Studio Code".
* Nombre del ejecutable: "winword" encuentra "Word".
* Tolerancia a letras salteadas ("phtshp" encuentra "Photoshop"), solo
  como ultimo recurso y siempre por debajo de cualquier coincidencia real.

Orden de los resultados
-------------------------
Por relevancia (coincidencia exacta > empieza por > empieza una palabra
> siglas > contiene > letras salteadas), y a igual relevancia: favoritas
primero, despues el nombre mas corto, despues alfabetico.
"""

import os
import re
import unicodedata

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")

# Puntaje por tipo de coincidencia de UNA palabra de la busqueda.
_EXACT = 100
_NAME_PREFIX = 90
_WORD_PREFIX = 75
_ACRONYM = 65
_SUBSTRING = 50
_FUZZY = 20

# Una coincidencia contra el nombre del ejecutable vale menos que la
# misma coincidencia contra el nombre visible.
_TARGET_WEIGHT = 0.6
_FAVORITE_BONUS = 4


def normalize(text) -> str:
    """Minusculas y sin acentos ('Cámara' -> 'camara', 'Ñandú' -> 'nandu')."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _words(normalized: str) -> list:
    return [w for w in _WORD_SPLIT.split(normalized) if w]


def _fuzzy(token: str, words: list) -> int:
    """Letras de 'token' en orden dentro del texto, empezando en el
    inicio de una palabra y sin saltos enormes. 0 si no encaja."""
    if len(token) < 3:
        return 0
    text = " ".join(words)
    starts = [0]
    for i, ch in enumerate(text):
        if ch == " ":
            starts.append(i + 1)
    for start in starts:
        pos = start
        ok = True
        for ch in token:
            pos = text.find(ch, pos)
            if pos < 0:
                ok = False
                break
            pos += 1
        if ok and (pos - start) <= len(token) * 2 + 2:
            return _FUZZY
    return 0


def _score_token(token: str, name: str, words: list, acronym: str) -> int:
    if name == token:
        return _EXACT
    if name.startswith(token):
        return _NAME_PREFIX
    if any(w.startswith(token) for w in words):
        return _WORD_PREFIX
    if len(token) >= 2 and acronym.startswith(token):
        return _ACRONYM
    if token in name:
        return _SUBSTRING
    return _fuzzy(token, words)


class _Indexed:
    """Datos de busqueda ya normalizados de una entrada (se calculan una
    sola vez por entrada y por busqueda, no por cada palabra)."""

    __slots__ = ("name", "words", "acronym", "exe", "exe_words")

    def __init__(self, entry: dict):
        self.name = normalize(entry.get("name"))
        self.words = _words(self.name)
        self.acronym = "".join(w[0] for w in self.words)
        target = entry.get("target")
        exe = ""
        if isinstance(target, str) and target.lower().endswith(".exe"):
            exe = normalize(os.path.splitext(target.replace("\\", "/").rsplit("/", 1)[-1])[0])
        self.exe = exe
        self.exe_words = _words(exe)


def score(entry: dict, tokens: list):
    """Puntaje de 'entry' para las palabras ya normalizadas de la
    busqueda, o None si alguna no aparece."""
    idx = _Indexed(entry)
    total = 0.0
    for token in tokens:
        best = _score_token(token, idx.name, idx.words, idx.acronym)
        if idx.exe:
            # Contra el ejecutable no hay siglas ni letras salteadas:
            # solo coincidencias literales, para no meter ruido.
            exe_score = 0
            if idx.exe == token:
                exe_score = _EXACT
            elif idx.exe.startswith(token) or any(w.startswith(token) for w in idx.exe_words):
                exe_score = _WORD_PREFIX
            elif token in idx.exe:
                exe_score = _SUBSTRING
            best = max(best, exe_score * _TARGET_WEIGHT)
        if not best:
            return None
        total += best
    if entry.get("favorite"):
        total += _FAVORITE_BONUS
    return total


def tokenize(query) -> list:
    return _words(normalize(query))


def search(entries, query) -> list:
    """Entradas que coinciden con 'query', de mas a menos relevante.
    Una busqueda vacia (o solo simbolos) no devuelve nada."""
    tokens = tokenize(query)
    if not tokens:
        return []
    ranked = []
    for entry in entries:
        value = score(entry, tokens)
        if value is None:
            continue
        name = normalize(entry.get("name"))
        ranked.append((-value, len(name), name, len(ranked), entry))
    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked]
