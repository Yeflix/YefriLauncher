"""
launcher_manager.py
---------------------
El corazon de la capa 'core': mantiene launchers.json. Fusiona lo que
detectan steam_detector, shortcut_scanner y uwp_detector con lo que el
usuario agrego o personalizo, y expone las operaciones de la interfaz
(categorias, favoritas, ocultar, fondo, lanzar).

Reglas que este modulo garantiza
----------------------------------
* Un escaneo nunca pisa lo que puso el usuario: las entradas manuales no
  se tocan, y en las detectadas se conservan los _PRESERVED_FIELDS y la
  categoria.
* Si una fuente FALLA en un escaneo (PowerShell no responde, el shell no
  contesta), sus apps se quedan como estaban.
* Si una app deja de detectarse (se desinstalo, se desactivo su fuente,
  se desconecto el disco), sale de la lista pero su personalizacion se
  guarda en 'remembered' y vuelve sola si la app reaparece.
* Todo acceso a self.data pasa por self._lock: el escaneo corre en otro
  hilo. Los metodos con sufijo '_unlocked' se llaman con el lock ya
  tomado (threading.Lock no es reentrante).
* Cada cambio se escribe al instante y de forma atomica.
"""

import json
import os
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor

from core import auto_categories, icon_extractor, shortcut_scanner, steam_detector, uwp_detector
from core.debug_log import log as _debug_log
from core.paths import ICON_CACHE_DIR, LAUNCHERS_PATH

# La categoria "por defecto": recibe las apps recien detectadas y las de
# una categoria que se elimina. Siempre existe, se puede renombrar pero
# no eliminar.
DEFAULT_GROUP_ID = "Group1"
DEFAULT_GROUP_TITLE = "Programas"
MAX_CATEGORY_TITLE_LEN = 40

_DEFAULT_DATA = {
    "groups": [
        {"group_id": DEFAULT_GROUP_ID, "title": DEFAULT_GROUP_TITLE, "launchers": []}
    ]
}

# Lo que el USUARIO puso sobre una entrada detectada y que un escaneo no
# puede pisar. Una personalizacion nueva (ej. un nombre propio) se agrega
# aca y queda protegida en todos los caminos: refresh(), re-agregar a
# mano y 'remembered'.
_PRESERVED_FIELDS = ("hidden", "hover_background", "favorite", "category_locked")

# type de una entrada detectada -> fuente que la produce.
_SOURCE_OF_TYPE = {"steam": "steam", "shortcut": "shortcuts", "uwp": "uwp"}

# Tope de apps desaparecidas cuya personalizacion se recuerda (se
# descartan las mas antiguas).
_MAX_REMEMBERED = 500

# Extraccion de iconos: I/O (disco + APIs de Windows), no calculo.
_ICON_EXTRACTION_WORKERS = 8


def _sort_entries(entries: list, sort_mode: str) -> list:
    """Ver LauncherManager.visible_groups() para el porque.

    Se ordena por (no_es_favorita, nombre) para que el bloque de
    favoritas quede arriba sin necesitar dos pasadas."""
    if sort_mode == "none":
        return list(entries)
    if sort_mode == "alphabetical":
        return sorted(entries, key=lambda e: _name_sort_key(e.get("name")))
    return sorted(
        entries,
        key=lambda e: (not e.get("favorite", False), _name_sort_key(e.get("name"))),
    )


def _name_sort_key(name):
    """Clave de orden alfabetico que se comporta como espera un usuario
    hispanohablante.

    casefold() solo no alcanza: ordena por codepoint Unicode, asi que
    'ámbar' cae DESPUES de 'Zoom' (la 'á' vive mas arriba en la tabla
    que cualquier letra ASCII). Se normaliza a NFKD y se descartan las
    marcas combinantes, con lo que 'á' pasa a ordenar como 'a' y 'ñ'
    como 'n'.

    Se devuelve una tupla (sin_acentos, original) para que dos nombres
    que solo difieren en acentos ('Peña' vs 'Pena') igual queden en un
    orden estable y no dependan del orden de llegada."""
    name = name or ""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(ch)
    )
    return (stripped.casefold(), name.casefold())


def _resolve_entry_icon(entry: dict, steam_path: str, cache_dir: str):
    """Resuelve el icono de UNA entrada. Pensado para correr dentro de
    un ThreadPoolExecutor (ver refresh() mas abajo), no en el hilo que
    lo llama.

    CoInitialize/CoUninitialize: SHGetFileInfo (uno de los caminos de
    icon_extractor.extract_icon, como ultimo recurso si ExtractIconEx no
    trajo nada) puede instanciar componentes COM del shell por detras, y
    COM exige que cada hilo que lo use se haya inicializado el mismo --
    un ThreadPoolExecutor crea hilos de Python lisos, sin eso por
    defecto, asi que hay que hacerlo a mano aca.

    Nunca deja pasar una excepcion: un icono que falla no debe tirar
    abajo el resto del pool (mismo criterio de robustez que ya usan
    steam_detector/shortcut_scanner/uwp_detector para no romper el
    escaneo completo por una sola entrada problematica)."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pythoncom = None

    try:
        icon_path = None
        if entry["type"] == "steam":
            if not steam_path:
                return
            appid = entry["id"].replace("steam_", "", 1)
            icon_path = icon_extractor.extract_steam_icon(steam_path, appid, cache_dir)

        elif entry["type"] == "uwp":
            # 'install_location' es solo un dato de trabajo para
            # resolver el icono ahora mismo -- no es parte del schema
            # persistido (ver docstring de uwp_detector.scan_uwp_apps),
            # asi que se saca del dict antes de que termine en
            # launchers.json.
            install_location = entry.pop("install_location", "")
            icon_path = icon_extractor.extract_uwp_icon(install_location, cache_dir)

        elif entry["type"] == "shortcut":
            # Igual que 'install_location': dato de trabajo, no se guarda.
            icon_location = entry.pop("icon_location", None) or ""
            path_part = icon_location.split(",")[0].strip()
            icon_source = icon_location if path_part else entry["target"]
            icon_path = icon_extractor.extract_icon(icon_source, cache_dir)

        if icon_path:
            entry["icon"] = icon_path
    except Exception as e:  # noqa: BLE001 - una entrada rota no debe tirar el pool completo
        _debug_log(f"_resolve_entry_icon: fallo con '{entry.get('name')}': {e}")
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


class LauncherManager:
    def __init__(self, config_path=None, cache_dir=None):
        self.config_path = config_path or LAUNCHERS_PATH
        self.cache_dir = cache_dir or ICON_CACHE_DIR
        self.data = {}
        # Resumen del ultimo refresh(), para que la interfaz sepa si hace
        # falta redibujar y que contarle al usuario. Ver refresh().
        self.last_refresh = {"changed": False, "added": 0, "removed": 0, "failed": []}
        self._lock = threading.Lock()
        self._load()
        self._log(
            f"__init__: config_path={self.config_path} "
            f"(existe={os.path.exists(self.config_path)}) -- "
            f"{sum(1 for _ in self._all_entries())} entrada(s), "
            f"{self._count_with_bg()} con imagen de fondo"
        )

    # ---------- diagnostico ----------
    # Log de texto plano junto a launchers.json. Propio (y no el de
    # core.debug_log) porque los tests usan un config_path distinto.
    _LOG_MAX_BYTES = 200_000

    def _log(self, message: str):
        try:
            log_path = os.path.join(os.path.dirname(self.config_path) or ".", "debug.log")
            if os.path.exists(log_path) and os.path.getsize(log_path) > self._LOG_MAX_BYTES:
                os.remove(log_path)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        except Exception:
            pass  # el log nunca debe romper la app

    def _count_with_bg(self) -> int:
        return sum(1 for e in self._all_entries() if e.get("hover_background"))

    # ---------- persistencia ----------

    def _load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("la raiz del archivo no es un objeto JSON")
                self.data = data
                self._normalize_data()
                return
            except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as e:
                # Un archivo ilegible no debe impedir arrancar: se aparta
                # una copia para investigar y se empieza de cero.
                self._log(f"_load(): '{self.config_path}' esta corrupto ({e}) -- se reinicia vacio")
                self._backup_corrupt_file(self.config_path)
        self.data = json.loads(json.dumps(_DEFAULT_DATA))  # copia profunda simple

    @staticmethod
    def _backup_corrupt_file(path: str):
        try:
            if os.path.exists(path):
                os.replace(path, path + ".corrupt")
        except OSError:
            pass

    def _save(self):
        """Escritura atomica: a un temporal en la misma carpeta y
        os.replace() al final. Una interrupcion a mitad de camino (kill,
        corte de luz) nunca deja launchers.json truncado."""
        directory = os.path.dirname(self.config_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = self.config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.config_path)

    def _all_entries(self):
        for group in self.data.get("groups", []):
            for entry in group.get("launchers", []):
                yield entry

    def _find_unlocked(self, entry_id: str):
        return next((e for e in self._all_entries() if e.get("id") == entry_id), None)

    # ---------- estructura de grupos (categorias) ----------

    @staticmethod
    def _new_group_id(taken: set) -> str:
        while True:
            gid = "cat_" + uuid.uuid4().hex[:8]
            if gid not in taken:
                return gid

    def _normalize_data(self):
        """Deja self.data con la forma que el resto del codigo asume:
        'groups' es una lista de grupos con group_id unico, title y
        launchers; cada entrada tiene un id unico y un nombre; el grupo
        por defecto siempre existe. Absorbe archivos editados a mano o
        dañados de una forma que sigue siendo JSON valido."""
        raw_groups = self.data.get("groups")
        if not isinstance(raw_groups, list):
            raw_groups = []

        seen_group_ids = set()
        seen_entry_ids = set()
        groups = []
        for raw in raw_groups:
            if not isinstance(raw, dict):
                continue
            gid = raw.get("group_id")
            if not isinstance(gid, str) or not gid or gid in seen_group_ids:
                gid = self._new_group_id(seen_group_ids)
            seen_group_ids.add(gid)

            title = raw.get("title")
            if not isinstance(title, str) or not title.strip():
                title = DEFAULT_GROUP_TITLE if gid == DEFAULT_GROUP_ID else gid

            launchers = []
            raw_launchers = raw.get("launchers")
            for entry in raw_launchers if isinstance(raw_launchers, list) else []:
                if not isinstance(entry, dict):
                    continue
                eid = entry.get("id")
                if not isinstance(eid, str) or not eid or eid in seen_entry_ids:
                    continue
                seen_entry_ids.add(eid)
                if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                    entry["name"] = eid
                launchers.append(entry)

            groups.append({**raw, "group_id": gid, "title": title, "launchers": launchers})

        self.data["groups"] = groups
        self._ensure_default_group()

        dismissed = self.data.get("dismissed_auto_rules")
        self.data["dismissed_auto_rules"] = sorted(
            {r for r in dismissed if isinstance(r, str)} if isinstance(dismissed, list) else set()
        )

        remembered = self.data.get("remembered")
        remembered = {
            eid: saved for eid, saved in remembered.items()
            if isinstance(eid, str) and isinstance(saved, dict)
        } if isinstance(remembered, dict) else {}
        self._store_remembered_unlocked(remembered)

    def _store_remembered_unlocked(self, remembered: dict):
        """'remembered' solo existe en el archivo si hay algo que recordar."""
        while len(remembered) > _MAX_REMEMBERED:
            del remembered[next(iter(remembered))]
        if remembered:
            self.data["remembered"] = remembered
        else:
            self.data.pop("remembered", None)

    def _ensure_default_group(self):
        """El lock ya esta tomado (o todavia no hay otros hilos, en _load)."""
        groups = self.data.get("groups")
        if not isinstance(groups, list):
            groups = self.data["groups"] = []
        if not any(g.get("group_id") == DEFAULT_GROUP_ID for g in groups):
            groups.insert(
                0, {"group_id": DEFAULT_GROUP_ID, "title": DEFAULT_GROUP_TITLE, "launchers": []}
            )

    def _group_unlocked(self, group_id: str):
        return next((g for g in self.data.get("groups", []) if g["group_id"] == group_id), None)

    def _title_error_unlocked(self, title, exclude_group_id=None) -> str:
        clean = (title or "").strip()
        if not clean:
            return "El nombre no puede estar vacío."
        if len(clean) > MAX_CATEGORY_TITLE_LEN:
            return f"El nombre no puede pasar de {MAX_CATEGORY_TITLE_LEN} caracteres."
        folded = clean.casefold()
        for group in self.data.get("groups", []):
            if group["group_id"] != exclude_group_id and group["title"].strip().casefold() == folded:
                return "Ya existe una categoría con ese nombre."
        return ""

    # ---------- deteccion ----------

    def _scan_sources(self, scan_steam: bool, scan_shortcuts: bool, scan_uwp: bool):
        """Corre los detectores habilitados. Devuelve (detectadas,
        fuentes_que_fallaron, steam_path). Un detector que lanza una
        excepcion o devuelve None cuenta como fuente fallida: no aporta
        nada, y refresh() conserva lo que ya habia de esa fuente."""
        detected = []
        failed = set()
        steam_path = ""

        def run(source: str, scan):
            try:
                found = scan()
            except Exception as e:  # noqa: BLE001 - una fuente rota no tira las demas
                self._log(f"refresh(): la fuente '{source}' fallo: {e!r}")
                found = None
            if found is None:
                failed.add(source)
            else:
                detected.extend(found)

        if scan_steam:
            # steam_path se resuelve una sola vez y se reusa para los iconos.
            try:
                steam_path = steam_detector.get_steam_path() or ""
            except Exception:  # noqa: BLE001
                steam_path = ""
            run("steam", lambda: steam_detector.scan_steam_library(steam_path))
        if scan_shortcuts:
            run("shortcuts", shortcut_scanner.scan_shortcuts)
        if scan_uwp:
            run("uwp", uwp_detector.scan_uwp_apps)
        return detected, failed, steam_path

    def refresh(self, scan_steam: bool = True, scan_shortcuts: bool = True, scan_uwp: bool = True,
                auto_rules=None) -> dict:
        """Re-escanea las fuentes habilitadas y fusiona con lo existente
        (ver las reglas en el docstring del modulo).

        auto_rules: ids de las reglas de categorizacion automatica a
        aplicar (ver core/auto_categories.py); None = las activas por
        defecto.

        Devuelve (y deja en self.last_refresh) un resumen:
        {"changed": bool, "added": int, "removed": int, "failed": [fuentes]}.
        Solo escribe el archivo si algo cambio."""
        # Escaneo y extraccion de iconos corren FUERA del lock: son
        # lentos (PowerShell, disco) y no tocan self.data. Con el lock
        # tomado bloquearian al hilo de la interfaz.
        detected, failed, steam_path = self._scan_sources(scan_steam, scan_shortcuts, scan_uwp)

        if detected:
            with ThreadPoolExecutor(max_workers=_ICON_EXTRACTION_WORKERS) as pool:
                list(pool.map(lambda e: _resolve_entry_icon(e, steam_path, self.cache_dir), detected))

        with self._lock:
            self._ensure_default_group()
            groups = self.data["groups"]
            before = json.dumps(self.data, sort_keys=True, ensure_ascii=False)

            # id -> (entrada, group_id de la categoria donde esta hoy)
            existing = {}
            for group in groups:
                for e in group["launchers"]:
                    existing[e["id"]] = (e, group["group_id"])
            manual_ids = {eid for eid, (e, _gid) in existing.items() if e.get("source") == "manual"}
            remembered = dict(self.data.get("remembered") or {})

            # Si el mismo id aparece dos veces en el escaneo gana la ultima.
            fresh = {}
            legacy_ids = {}
            for entry in detected:
                legacy_id = entry.pop("legacy_id", None)  # dato de trabajo, no se guarda
                if entry["id"] in manual_ids:
                    continue
                fresh[entry["id"]] = entry
                if legacy_id:
                    legacy_ids[entry["id"]] = legacy_id

            # Las manuales: intactas, en su categoria y su orden.
            new_lists = {g["group_id"]: [] for g in groups}
            for group in groups:
                for e in group["launchers"]:
                    if e["id"] in manual_ids:
                        new_lists[group["group_id"]].append(e)

            added = 0
            claimed = set()  # ids viejos cuya personalizacion paso a un id nuevo
            for eid, entry in fresh.items():
                target_gid = DEFAULT_GROUP_ID
                previous = existing.get(eid)
                if previous is None:
                    # Un acceso directo con argumentos cambio de id (ver
                    # shortcut_scanner): hereda lo de su id anterior.
                    legacy_id = legacy_ids.get(eid)
                    if (legacy_id and legacy_id not in fresh and legacy_id not in claimed
                            and legacy_id not in manual_ids and legacy_id in existing):
                        previous = existing[legacy_id]
                        claimed.add(legacy_id)

                if previous is not None:
                    prev_entry, prev_gid = previous
                    for field in _PRESERVED_FIELDS:
                        if prev_entry.get(field):
                            entry[field] = prev_entry[field]
                    if prev_gid in new_lists:
                        target_gid = prev_gid
                    if entry == prev_entry:
                        entry = prev_entry  # sin cambios: se conserva el mismo objeto
                else:
                    added += 1
                    saved = remembered.get(eid)
                    if isinstance(saved, dict):  # la app volvio: recupera lo suyo
                        for field in _PRESERVED_FIELDS:
                            if saved.get(field):
                                entry[field] = saved[field]
                        if saved.get("group_id") in new_lists:
                            target_gid = saved["group_id"]
                remembered.pop(eid, None)
                new_lists[target_gid].append(entry)

            removed = 0
            for eid, (entry, gid) in existing.items():
                if eid in manual_ids or eid in fresh or eid in claimed:
                    continue
                if _SOURCE_OF_TYPE.get(entry.get("type")) in failed:
                    new_lists[gid].append(entry)  # su fuente fallo: se queda como estaba
                    continue
                removed += 1
                saved = {f: entry[f] for f in _PRESERVED_FIELDS if entry.get(f)}
                if gid != DEFAULT_GROUP_ID:
                    saved["group_id"] = gid
                if saved:
                    remembered.pop(eid, None)  # al final de la cola: es la mas reciente
                    remembered[eid] = saved

            for group in groups:
                group["launchers"] = new_lists[group["group_id"]]
            self._store_remembered_unlocked(remembered)

            # Despues de repartir: las reglas ven tanto lo recien
            # detectado como lo que ya estaba en la categoria por defecto.
            moved = self._apply_auto_rules_unlocked(self._enabled_rules(auto_rules))

            changed = json.dumps(self.data, sort_keys=True, ensure_ascii=False) != before
            if changed:
                self._save()
            summary = {
                "changed": changed, "added": added, "removed": removed,
                "failed": sorted(failed),
            }
            self.last_refresh = summary
            icons_in_use = [e.get("icon") for e in self._all_entries()]
            self._log(
                f"refresh(): {sum(len(v) for v in new_lists.values())} entrada(s), "
                f"+{added} -{removed}, {moved} movida(s) por reglas, "
                f"fallaron={sorted(failed)}, cambio={changed}"
            )

        icon_extractor.prune_cache(self.cache_dir, [i for i in icons_in_use if i and i != "auto"])
        return summary

    # ---------- edicion manual ----------

    def add_manual_entry(self, entry: dict, group_id=None):
        """Guarda la entrada ya, sin extraer su icono (eso es
        resolve_manual_icon, pensado para correr en otro hilo).

        Si ya existia una entrada con el mismo id se conserva su
        personalizacion. group_id: categoria destino; None o una que no
        existe = la que ya tenia, o la categoria por defecto."""
        entry = dict(entry)
        entry["source"] = "manual"

        with self._lock:
            self._ensure_default_group()

            previous, previous_gid = None, None
            for group in self.data["groups"]:
                found = next((e for e in group["launchers"] if e["id"] == entry["id"]), None)
                if found is not None:
                    previous, previous_gid = found, group["group_id"]
                    break

            if previous is not None:
                for field in _PRESERVED_FIELDS:
                    if previous.get(field):
                        entry[field] = previous[field]

            target = self._group_unlocked(group_id) if group_id else None
            if target is None and previous_gid is not None:
                target = self._group_unlocked(previous_gid)
            if target is None:
                target = self._group_unlocked(DEFAULT_GROUP_ID)

            # Se saca de TODAS las categorias: re-agregada en otra, no
            # puede quedar duplicada.
            for group in self.data["groups"]:
                group["launchers"] = [e for e in group["launchers"] if e["id"] != entry["id"]]
            target["launchers"].append(entry)
            self._save()

    def resolve_manual_icon(self, entry_id: str) -> bool:
        """Extrae el icono de una entrada manual ya guardada. Lento:
        pensado para un hilo de fondo. True si el icono cambio."""
        with self._lock:
            entry = self._find_unlocked(entry_id)
            if entry is None:
                return False
            target = entry.get("target")
            if entry.get("icon") not in (None, "auto") or not target:
                return False  # ya tiene icono propio, o no hay de donde sacarlo

        icon_path = icon_extractor.extract_icon(target, self.cache_dir)  # fuera del lock
        if not icon_path:
            return False

        with self._lock:
            # Se vuelve a buscar: un refresh() pudo reemplazar la lista
            # mientras se extraia el icono.
            current = self._find_unlocked(entry_id)
            if current is None:
                return False
            current["icon"] = icon_path
            self._save()
        return True

    # ---------- consultas ----------

    def get_entry(self, entry_id: str):
        """Copia de la entrada, o None. Para mostrar su nombre en un
        aviso sin quedarse con una referencia a self.data."""
        with self._lock:
            entry = self._find_unlocked(entry_id)
            return dict(entry) if entry is not None else None

    def hidden_entries(self) -> list:
        """Entradas ocultas (para restaurarlas desde Configuracion)."""
        with self._lock:
            return [e for e in self._all_entries() if e.get("hidden")]

    def visible_groups(self, sort_mode: str = "favorites_first") -> list:
        """Las categorias, sin las entradas ocultas y ya ordenadas: lo
        que se muestra en la lista. Incluye las categorias vacias (la
        lista principal las salta; Configuracion no). Cada categoria se
        ordena por separado.

        sort_mode: "favorites_first" (favoritas arriba, cada bloque
        alfabetico), "alphabetical", o "none" (orden de deteccion)."""
        with self._lock:
            result = []
            for group in self.data.get("groups", []):
                launchers = [e for e in group.get("launchers", []) if not e.get("hidden")]
                result.append({**group, "launchers": _sort_entries(launchers, sort_mode)})
            return result

    def is_favorite(self, entry_id: str) -> bool:
        with self._lock:
            return any(e["id"] == entry_id and e.get("favorite") for e in self._all_entries())

    # ---------- personalizacion de una entrada ----------
    # Todas devuelven True si la entrada existe. Los campos se quitan en
    # vez de guardarse en False/"" para no llenar el archivo de valores
    # por defecto.

    def _set_field(self, entry_id: str, field: str, value) -> bool:
        with self._lock:
            entry = self._find_unlocked(entry_id)
            if entry is None:
                return False
            if value:
                if entry.get(field) == value:
                    return True
                entry[field] = value
            else:
                if field not in entry:
                    return True
                entry.pop(field, None)
            self._save()
            return True

    def hide_entry(self, entry_id: str) -> bool:
        """Quita la entrada de la lista sin borrarla (se restaura con
        unhide_entry)."""
        return self._set_field(entry_id, "hidden", True)

    def unhide_entry(self, entry_id: str) -> bool:
        return self._set_field(entry_id, "hidden", False)

    def set_favorite(self, entry_id: str, favorite: bool) -> bool:
        return self._set_field(entry_id, "favorite", bool(favorite))

    def set_hover_background(self, entry_id: str, image_path: str) -> bool:
        """image_path vacio quita la imagen asignada."""
        return self._set_field(entry_id, "hover_background", image_path or "")

    # ---------- categorias ----------
    # Una categoria ES un grupo de launchers.json ('groups'): no hay
    # ningun modelo de datos nuevo, solo la logica para crearlos,
    # renombrarlos, ordenarlos y mover entradas entre ellos. Las
    # entradas viven fisicamente dentro del grupo al que pertenecen, asi
    # que un launchers.json de la v1 sigue siendo valido sin migrar
    # nada. Todas las funciones que escriben toman el lock, como el
    # resto de la persistencia (ver self._lock en __init__).

    @staticmethod
    def _enabled_rules(auto_rules) -> frozenset:
        return auto_categories.DEFAULT_ENABLED if auto_rules is None else frozenset(auto_rules)

    def _group_for_rule_unlocked(self, rule, dismissed: set):
        """La categoria donde deben caer las apps de 'rule', creandola si
        hace falta. En orden: la que ya tiene el id de la regla (aunque
        el usuario la haya renombrado); una que el usuario creo a mano
        con el mismo nombre (se ADOPTA en vez de duplicar el titulo); y
        recien si no hay ninguna, crear una nueva -- salvo que el usuario
        haya eliminado esa categoria a proposito (ver delete_category),
        en cuyo caso None: las apps se quedan en la por defecto."""
        group = self._group_unlocked(rule.group_id)
        if group is not None:
            return group
        folded = rule.title.casefold()
        group = next(
            (g for g in self.data["groups"] if g["title"].strip().casefold() == folded), None
        )
        if group is not None:
            return group
        if rule.rule_id in dismissed:
            return None
        group = {"group_id": rule.group_id, "title": rule.title, "launchers": []}
        self.data["groups"].append(group)
        return group

    def _apply_auto_rules_unlocked(self, enabled) -> int:
        """El lock ya esta tomado. Mueve a su categoria las apps
        DETECTADAS (nunca las manuales) que hoy estan en la categoria por
        defecto y que el usuario no fijo a mano (category_locked).
        Devuelve cuantas movio. Idempotente: correrlo dos veces seguidas
        no cambia nada la segunda."""
        rules = [r for r in auto_categories.RULES if r.rule_id in enabled]
        if not rules:
            return 0
        self._ensure_default_group()
        default = self._group_unlocked(DEFAULT_GROUP_ID)
        dismissed = set(self.data.get("dismissed_auto_rules") or [])

        moved = 0
        for entry in list(default["launchers"]):
            if entry.get("source") != "auto" or entry.get("category_locked"):
                continue
            rule = next((r for r in rules if r.matches(entry)), None)
            if rule is None:
                continue
            target = self._group_for_rule_unlocked(rule, dismissed)
            if target is None or target is default:
                continue
            default["launchers"].remove(entry)
            target["launchers"].append(entry)
            moved += 1
        return moved

    def apply_auto_categories(self, auto_rules=None) -> int:
        """Aplica ahora las reglas automaticas a lo que ya esta cargado,
        sin re-escanear (lo usa Configuracion al guardar, para que
        activar una regla surta efecto al instante). Devuelve cuantas
        apps movio."""
        with self._lock:
            moved = self._apply_auto_rules_unlocked(self._enabled_rules(auto_rules))
            if moved:
                self._save()
            return moved

    def categories(self) -> list:
        """Todas las categorias en su orden de visualizacion:
        [{group_id, title, count, is_default}]. 'count' no incluye las
        apps ocultas (son las que el usuario ve en la lista)."""
        with self._lock:
            return [
                {
                    "group_id": g["group_id"],
                    "title": g["title"],
                    "count": sum(1 for e in g["launchers"] if not e.get("hidden")),
                    "is_default": g["group_id"] == DEFAULT_GROUP_ID,
                }
                for g in self.data.get("groups", [])
            ]

    def category_of(self, entry_id: str):
        """group_id de la categoria donde esta la entrada, o None."""
        with self._lock:
            for group in self.data.get("groups", []):
                if any(e["id"] == entry_id for e in group["launchers"]):
                    return group["group_id"]
        return None

    def check_category_title(self, title: str, exclude_group_id=None) -> str:
        """'' si el nombre es valido; si no, el mensaje para mostrarle al
        usuario (vacio, demasiado largo, o repetido -- sin distinguir
        mayusculas). exclude_group_id: la categoria que se esta
        renombrando, para que su propio nombre actual no cuente como
        repetido."""
        with self._lock:
            return self._title_error_unlocked(title, exclude_group_id)

    def create_category(self, title: str) -> str:
        """Crea una categoria vacia al final y devuelve su group_id.
        ValueError con un mensaje legible si el nombre no es valido (la
        UI pre-valida con check_category_title; esto es la red de
        seguridad para que nunca se guarde algo invalido)."""
        with self._lock:
            error = self._title_error_unlocked(title)
            if error:
                raise ValueError(error)
            self._ensure_default_group()
            taken = {g["group_id"] for g in self.data["groups"]}
            gid = self._new_group_id(taken)
            self.data["groups"].append({"group_id": gid, "title": title.strip(), "launchers": []})
            self._save()
            return gid

    def rename_category(self, group_id: str, title: str) -> bool:
        """False si la categoria no existe. ValueError si el nombre no
        es valido (ver create_category)."""
        with self._lock:
            group = self._group_unlocked(group_id)
            if group is None:
                return False
            error = self._title_error_unlocked(title, exclude_group_id=group_id)
            if error:
                raise ValueError(error)
            group["title"] = title.strip()
            self._save()
            return True

    def delete_category(self, group_id: str) -> bool:
        """Elimina una categoria; sus apps NO se borran, pasan a la
        categoria por defecto. False si no existe o si es la categoria
        por defecto (esa no se puede eliminar)."""
        if group_id == DEFAULT_GROUP_ID:
            return False
        with self._lock:
            group = self._group_unlocked(group_id)
            if group is None:
                return False
            self._ensure_default_group()
            self._group_unlocked(DEFAULT_GROUP_ID)["launchers"].extend(group["launchers"])
            self.data["groups"] = [g for g in self.data["groups"] if g["group_id"] != group_id]
            # Si era la categoria de una regla automatica, se recuerda que
            # el usuario la quiso fuera: sin esto, el proximo Steam nuevo
            # detectado la volveria a crear y eliminarla seria inutil. Si
            # mas adelante crea a mano una categoria con ese nombre, la
            # regla la adopta (ver _group_for_rule_unlocked).
            rule = auto_categories.rule_for_group(group_id, group["title"])
            if rule is not None:
                dismissed = set(self.data.get("dismissed_auto_rules") or [])
                dismissed.add(rule.rule_id)
                self.data["dismissed_auto_rules"] = sorted(dismissed)
            self._save()
            return True

    def move_category(self, group_id: str, delta: int) -> bool:
        """Sube (delta<0) o baja (delta>0) una categoria en el orden de
        visualizacion. False si no existe o ya esta en el borde."""
        with self._lock:
            groups = self.data.get("groups", [])
            index = next((i for i, g in enumerate(groups) if g["group_id"] == group_id), None)
            if index is None:
                return False
            new_index = index + delta
            if delta == 0 or not 0 <= new_index < len(groups):
                return False
            groups.insert(new_index, groups.pop(index))
            self._save()
            return True

    def move_entry_to_category(self, entry_id: str, group_id: str) -> bool:
        """Mueve una app (detectada o manual) a otra categoria. Devuelve
        True si la app queda en esa categoria (incluye el caso de que ya
        estuviera ahi); False si la app o la categoria no existen.
        Mover a mano fija la app a su categoria: las reglas automaticas
        (core/auto_categories.py) no la vuelven a mover."""
        with self._lock:
            target = self._group_unlocked(group_id)
            if target is None:
                return False
            for group in self.data["groups"]:
                for entry in group["launchers"]:
                    if entry["id"] != entry_id:
                        continue
                    # El usuario eligio ESTE lugar para la app: las reglas
                    # automaticas ya no la tocan (ver _PRESERVED_FIELDS).
                    changed = not entry.get("category_locked")
                    entry["category_locked"] = True
                    if group is not target:
                        group["launchers"].remove(entry)
                        target["launchers"].append(entry)
                        changed = True
                    if changed:
                        self._save()
                    return True
        return False

    # ---------- lanzamiento ----------

    def launch(self, entry_id: str):
        """Lanza el programa. Nunca propaga una excepcion. Devuelve:
        - True/False: se lanzo (el valor es close_after_launch, que la
          interfaz ya no usa).
        - None: no se pudo lanzar (no existe la entrada, la app se
          desinstalo, permiso denegado...). El motivo queda en debug.log.

        Los accesos directos se abren por su .lnk ('launch') para
        respetar argumentos, carpeta de trabajo y permisos; si ese .lnk
        ya no existe se abre el ejecutable ('target')."""
        # El lock solo cubre la busqueda: abrir un proceso externo puede
        # tardar y no debe bloquear un refresh() concurrente.
        with self._lock:
            entry = self._find_unlocked(entry_id)
            if entry is not None:
                entry = dict(entry)
        if entry is None:
            self._log(f"launch(): entry_id={entry_id!r} no encontrado, no se lanza nada")
            return None

        candidates = []
        shortcut = entry.get("launch")
        if isinstance(shortcut, str) and shortcut and os.path.exists(shortcut):
            candidates.append(shortcut)
        target = entry.get("target")
        if isinstance(target, str) and target:
            candidates.append(target)

        error = "la entrada no tiene destino"
        for path in candidates:
            try:
                os.startfile(path)  # .exe, .lnk, steam:// y shell:
            except Exception as e:  # noqa: BLE001 - un destino roto no debe romper la app
                error = repr(e)
                continue
            return bool(entry.get("close_after_launch", False))

        self._log(f"launch(): no se pudo abrir '{entry.get('name')}' ({candidates}): {error}")
        return None
