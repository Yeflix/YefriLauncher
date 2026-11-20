# SPECTRUM Launcher — Documentación

Launcher de escritorio para Windows, portado desde una skin de Rainmeter
a una app nativa en Python + PySide6. Vive en la bandeja del sistema
como un panel flotante sin bordes, con una lista de apps y juegos
detectados automáticamente (Steam, accesos directos del Menú Inicio,
apps de Microsoft Store) más lo que el usuario agregue a mano.

Este documento reúne en un solo lugar qué hace el proyecto, cómo está
armado, y qué decisiones de diseño explican por qué está armado así.

> **Estado actual**: la v1 está cerrada y estable. La v2 incorporó
> **categorías** de punta a punta: modelo de datos y lógica de
> `LauncherManager` (con tests), menú contextual de las tarjetas,
> selector en "Agregar app", página propia en Configuración y
> **categorización automática** (los juegos de Steam van solos a "Juegos"). De paso
> se corrigieron tres bugs de la v1 que se descubrieron al construirlas
> (ver [Historial de estabilidad](#historial-de-estabilidad-por-qué-el-código-se-ve-así)).
> Después de eso se hizo una ronda de **optimización** (rendimiento,
> concurrencia, funcionalidad, responsive y textos) a partir de un
> análisis pedido por el usuario — ver
> [Optimización: rendimiento, funcionalidad, responsive y textos](#optimización-rendimiento-funcionalidad-responsive-y-textos).
> Lo que queda está en [Ideas para v2](#ideas-para-v2).

---

## Índice

1. [Instalación](#instalación)
2. [Estructura del proyecto](#estructura-del-proyecto)
3. [Funcionalidades](#funcionalidades)
4. [Categorías (v2)](#categorías-v2)
5. [Decisiones de diseño](#decisiones-de-diseño)
6. [Modelo de datos](#modelo-de-datos)
7. [Historial de estabilidad](#historial-de-estabilidad-por-qué-el-código-se-ve-así)
8. [Optimización: rendimiento, funcionalidad, responsive y textos](#optimización-rendimiento-funcionalidad-responsive-y-textos)
9. [Dependencias](#dependencias)
10. [Tests](#tests)
11. [Limitaciones conocidas](#limitaciones-conocidas)
12. [Ideas para v2](#ideas-para-v2)

---

## Instalación

```
pip install -r requirements.txt
python main.py
```

La primera vez, `settings.json` y `launchers.json` se generan solos en
`%APPDATA%\SpectrumLauncher\config\` (si ya tenías una carpeta `config/`
junto al proyecto, se copia ahí automáticamente, una sola vez). **Los datos
del usuario ya no viven dentro de la carpeta del proyecto**: se puede
reemplazar o volver a descomprimir el código sin perder imágenes de fondo,
favoritas ni categorías. Para usar otra ubicación: variable de entorno
`SPECTRUM_DATA_DIR`. El programa queda corriendo en la bandeja del sistema;
la única forma de cerrarlo del todo es "Cerrar" desde ese menú (Escape,
click en una app, etc. solo ocultan la ventana).

La detección de apps de Microsoft Store requiere Windows PowerShell
(incluido por defecto en Windows 10 y 11); se puede desactivar desde
Configuración → Detección si por algún motivo no está disponible.

**Empaquetado a `.exe`** (PyInstaller):

```
pip install pyinstaller
python tools/make_icon.py          # una sola vez: genera assets/icons/spectrum.ico
pyinstaller --noconfirm main.spec
```

Resultado: `dist\SpectrumLauncher\SpectrumLauncher.exe`. Hay que distribuir
la **carpeta completa**, no solo el `.exe`. Sin consola (app de bandeja);
UPX desactivado a propósito (falsos positivos de antivirus). Variables
opcionales: `set SPECTRUM_CONSOLE=1` para un build de depuración con consola,
y `set SPECTRUM_ONEFILE=1` para un único `.exe` (arranca más lento). Los
datos del usuario viven en `%APPDATA%\SpectrumLauncher`, así que reemplazar
la carpeta `dist` por una versión nueva no los toca. Iniciar con Windows y
un instalador quedan fuera de este repo.

---

## Estructura del proyecto

```
spectrum_launcher/
├── main.py                    # punto de entrada
├── main.spec                  # config de PyInstaller (carpeta / onefile / consola por variables de entorno)
├── requirements.txt
├── PROYECTO.md                 # este archivo
├── config/
│   ├── settings.json          # ventana, animación, detección, reglas de categorización, orden, atajo (se genera solo)
│   ├── launchers.json         # apps detectadas + manuales (se genera solo)
│   └── launchers.schema.json  # plantilla de referencia (no la lee el programa): un ejemplo de cada tipo de entrada + categorías
├── core/                       # lógica pura, sin UI — todo lo que podría testearse sin Windows
│   ├── paths.py                # rutas absolutas; datos del usuario en %APPDATA% + migración desde config/ vieja
│   ├── debug_log.py            # log a archivo compartido, reemplaza los print() invisibles
│   ├── config_manager.py       # load/save de settings.json, con merge de defaults
│   ├── auto_categories.py      # reglas que mandan apps recién detectadas a una categoría (Juegos, Microsoft Store)
│   ├── launcher_manager.py     # el corazón: fusiona detección + manual, categorías, orden, favoritas, lock
│   ├── steam_detector.py       # lee libraryfolders.vdf / appmanifest_*.acf
│   ├── shortcut_scanner.py     # escanea .lnk del Menú Inicio y el Escritorio
│   ├── uwp_detector.py         # apps de Microsoft Store vía PowerShell (Get-StartApps)
│   ├── icon_extractor.py       # ExtractIconEx → SHGetFileInfo → logo de paquete UWP → Steam
│   ├── scan_worker.py          # corre refresh() en un QThread aparte
│   └── single_instance.py      # evita dos copias corriendo a la vez
├── ui/                          # PySide6
│   ├── main_window.py           # ventana, bandeja, scroll, búsqueda, handlers de tarjetas
│   ├── launcher_card.py         # tarjeta individual (hover, mini-botones, imagen de fondo)
│   ├── virtual_card_list.py     # pool reciclado de tarjetas + títulos de categoría para listas grandes
│   ├── expand_overlay.py        # panel "agrandado" al pasar el mouse por la flecha
│   ├── special_button.py        # botón "Agregar app" / "Configuración" (pulso continuo)
│   ├── add_app_dialog.py        # diálogo para agregar una app a mano (con selector de categoría)
│   ├── category_dialogs.py      # pedir el nombre de una categoría (compartido por menú y Configuración)
│   ├── settings_window.py       # panel de Configuración, navegación lateral (incluye la página Categorías)
│   ├── app_icon.py              # genera el ícono del programa/bandeja por código
│   └── global_hotkey.py         # atajo global (Windows, vía ctypes)
├── tests/
│   ├── conftest.py              # stubea los módulos nativos de Windows para correr en cualquier SO
│   ├── test_core.py             # 60 tests de core/: bugs históricos + categorías + reglas automáticas
│   └── test_ui.py               # 14 tests de ui/ en modo offscreen (se saltean solos sin PySide6)
└── tools/
    ├── make_icon.py              # genera assets/icons/spectrum.ico desde ui/app_icon.py
    ├── diagnose_steam.py         # script standalone para depurar detección de Steam
    └── diagnose_steam_icons.py
```

**≈6.400 líneas de Python** en 22 módulos. El más grande, `main_window.py`
(~1.130 líneas), sigue siendo el candidato más claro a seguir partiendo
si crece más (ver [Ideas para v2](#ideas-para-v2)).

---

## Funcionalidades

### Detección híbrida de programas

Tres fuentes, cada una activable/desactivable por separado desde
Configuración → Detección:

- **Steam** (`steam_detector.py`): lee `libraryfolders.vdf` para
  encontrar todas las bibliotecas (no solo la default), y cada
  `appmanifest_*.acf` para nombre + AppID. Ícono cacheado propio de
  cada juego.
- **Accesos directos** (`shortcut_scanner.py`): recorre el Menú Inicio
  (usuario + todos los usuarios) y el Escritorio, resolviendo cada
  `.lnk` vía `WScript.Shell` (COM). El id de cada entrada es un hash
  del **path normalizado** del ejecutable (`os.path.normpath` +
  minúsculas) — esto importa porque el id tiene que ser estable entre
  escaneos para no perder personalización (ver más abajo).
- **Microsoft Store / UWP** (`uwp_detector.py`): estas apps no tienen
  un `.lnk` normal (su target queda vacío para `WScript.Shell`), así
  que se piden directo al shell con `Get-StartApps` de PowerShell,
  cruzado con `Get-AppxPackage` en la misma llamada para poder resolver
  el ícono real. Se lanzan con `shell:AppsFolder\<AppUserModelID>`.
  Nombres declarados como referencia indirecta a un recurso
  (`ms-resource:...`, común en apps de Microsoft) se resuelven con
  `SHLoadIndirectString`; si eso falla, se arma un nombre legible a
  partir del identificador del paquete en vez de mostrar el string
  técnico sin resolver.

El escaneo completo corre en un `QThread` aparte
(`core/scan_worker.py`) para no bloquear el arranque. La extracción de
íconos usa un `ThreadPoolExecutor` (8 hilos) en vez de un bucle
secuencial — ~7x más rápido en el escaneo "en frío" (apps nunca
vistas, sin nada todavía en `cache/extracted_icons/`).

### Fusión sin pisar lo manual

Cada `refresh()` (arranque, o "Buscar de nuevo ahora" en Configuración)
vuelve a escanear las tres fuentes y fusiona el resultado con lo que ya
había, preservando:
- Entradas con `source: "manual"` (agregadas a mano): nunca se tocan.
- `hidden` y `hover_background` de entradas detectadas automáticamente,
  aunque no sean manuales.
- Lo mismo al re-agregar a mano una app que ya existía: no se pierde su
  personalización.

### Apps agregadas a mano

"Agregar app" abre un diálogo que valida campos vacíos y avisa (con
opción de continuar igual) si la ruta no existe. La resolución del
ícono corre en background, no al cerrar el diálogo.

### Orden y favoritas

Clic derecho sobre una tarjeta → "Marcar como favorita". Configuración
→ General tiene un selector de orden:
- **Favoritas primero, luego alfabético** (default).
- **Alfabético.**
- **Orden de detección** (sin ordenar — el comportamiento original).

El orden alfabético normaliza acentos y eñes para que ordenen donde un
hispanohablante espera (`ámbar` antes que `Blender`, no después de
`Zoom`).

### Ocultar / restaurar

Clic derecho → "Quitar de la lista" (o el botón X en hover) no borra la
entrada, la marca `hidden`. Configuración → Apps ocultas tiene la lista
completa para restaurar.

### Imagen de fondo personalizada

Clic derecho → "Asignar imagen de fondo...". Aparece tras ~2s de hover
sostenido, con una animación de revelado propia. Se guarda por entrada
en `launchers.json` (campo `hover_background`) y sobrevive a rescans y
reinicios.

### Animación de hover

Una propiedad Qt animable (`hoverProgress`) controla en paralelo alto
visual (sin relayout — ver Decisiones de diseño), color, desplazamiento
horizontal opcional, y un flash breve al hacer click. 8 curvas de
easing, cada una con su propio multiplicador de duración. El panel de
Configuración tiene una vista previa en vivo que se anima sola en loop.

### Scroll infinito (listas chicas) / virtualización (listas grandes)

Por debajo de 60 apps visibles en total: 3 copias completas de la
lista apiladas, con un salto silencioso al llegar al borde real —
scroll infinito clásico.

A partir de 60 apps (sumando **todas** las categorías): un pool
reciclado de ~15-20 tarjetas más un pool de títulos
(`virtual_card_list.py`), dimensionados al viewport visible y no al
total de apps. La lista se aplana en filas de dos alturas (título de
categoría / tarjeta) con una tabla de offsets acumulados. El pool
se autocorrige si la estimación inicial del tamaño de ventana quedó
corta, y re-coloca sus filas si el ancho del contenedor cambia. Esta
versión no hace loop — para una lista tan grande, el buscador es la
forma principal de navegar. Al reconstruir la lista (ej. mover una app
de categoría) se conserva la posición de scroll.

No se virtualiza con una búsqueda activa (el resultado filtrado es
chico) ni con los botones especiales puestos "Dentro de la lista".

Ambos caminos comparten el mismo mecanismo de corrección de hover (ver
más abajo).

### Panel de tarjeta expandida

El botón de flecha (aparece en hover) abre un panel flotante más grande
con la imagen de fondo ampliada, deslizándose desde el borde de la
ventana — vive en `ui/expand_overlay.py`, como su propia ventana (no un
widget hijo, para no quedar recortado por el ancho de la ventana
principal).

### Búsqueda

Caja de texto arriba de la lista, filtra por nombre con debounce
(140ms). Mientras hay una búsqueda activa se usa una sola copia sin
loop infinito ni virtualización — no tiene sentido para un resultado
filtrado.

### Panel de Configuración

Navegación lateral por secciones (General / Detección / Animación /
Botones / Categorías / Apps ocultas / Atajos) en vez de una columna larga. Incluye:
tamaño de tarjeta (con ícono y fuente que escalan proporcionalmente),
orden de la lista, opacidad de fondo, siempre-visible, tooltips,
detección por fuente + reescaneo manual, las 8 curvas de animación con
vista previa en vivo, ubicación de los botones especiales, gestión de
categorías, deshacer apps ocultas, y el atajo global (editable, se aplica en caliente sin
reiniciar).

### Bandeja del sistema + atajo global

`Qt.WindowType.Tool` (no aparece en la barra de tareas). Cerrar/Escape
solo ocultan. El menú de la bandeja incluye **Abrir carpeta de datos**
(abre `%APPDATA%\SpectrumLauncher` en el Explorador). Atajo configurable (default `Ctrl+Alt+Espacio`) muestra
u oculta la ventana desde cualquier lugar, tenga o no el foco.

### Instancia única

Un `QLocalServer` (named pipe) evita que se abran dos copias a la vez.
Si se vuelve a lanzar el `.exe` estando ya abierto, la copia nueva le
avisa a la que ya corría para que se muestre, y se cierra sin abrir
una ventana propia.

---

## Categorías (v2)

Las apps se agrupan en **categorías**, cada una con su propio título
en la lista. Una categoría *es* un grupo de `launchers.json`
(`groups[]`): no hay un modelo de datos nuevo, así que un archivo de la
v1 (un único `Group1`) sigue siendo válido sin migrar nada.

**Cómo se usa**
- **Mover una app**: clic derecho sobre la tarjeta → *Mover a categoría*
  → elegir una (la actual aparece tildada y deshabilitada) o
  *Nueva categoría...* (la crea y mueve la app ahí de una vez).
- **Agregar app**: si hay más de una categoría, el diálogo muestra un
  selector (por defecto, la categoría por defecto).
- **Configuración → Categorías**: crear, renombrar, subir/bajar (orden
  de aparición en la lista) y eliminar. Estos cambios se aplican al
  momento, sin depender de *Guardar* (igual que restaurar apps
  ocultas).

**Reglas**
- **Categoría por defecto** (`Group1`, "Programas" por defecto): siempre
  existe, se puede renombrar pero no eliminar. Recibe las apps recién
  detectadas que no encajan en una regla automática y las de una categoría que se elimina — eliminar una
  categoría **nunca borra apps**, las devuelve a la por defecto.
- **Los rescans respetan la categoría**: cada app detectada se queda en
  la categoría donde el usuario la puso; una app que ya no se detecta
  (desinstalada) desaparece de donde estuviera. Las apps manuales
  nunca se tocan.
- **Nombres**: no vacíos, hasta 40 caracteres, únicos sin distinguir
  mayúsculas. La validación vive en un solo lugar
  (`LauncherManager.check_category_title`); `create_category` y
  `rename_category` lanzan `ValueError` como red de seguridad.
- **Orden dentro de cada categoría**: el modo de orden elegido
  (favoritas primero / alfabético / detección) se aplica por
  separado en cada categoría; las favoritas suben dentro de la suya.
- **Categorías vacías**: existen (se ven en Configuración) pero no se
  muestran en la lista principal.

**Categorización automática** (`core/auto_categories.py`)

Las apps *detectadas* (nunca las manuales) se mandan solas a una
categoría según una regla. Vienen dos:

| Regla | Categoría | Qué detecta | Por defecto |
|---|---|---|---|
| `games` | Juegos | `type == "steam"`; launchers de juegos (Steam, Epic, GOG Galaxy, Battle.net, Ubisoft Connect, EA app/Origin, Riot, itch) y accesos directos cuyo ejecutable esté en una carpeta de biblioteca de esas tiendas (`steamapps\common`, `Epic Games`, `GOG Games`, `Riot Games`...) | activada |
| `store` | Microsoft Store | `type == "uwp"` | desactivada |

- **Solo actúa sobre apps que siguen en la categoría por defecto y que
  el usuario no movió a mano.** Mover una app a mano la *fija*
  (`category_locked` en su entrada; también vale dejarla a propósito en
  la por defecto): las reglas no la vuelven a tocar.
- **Retroactiva e idempotente**: corre en cada `refresh()` sobre todo lo
  que hay en la categoría por defecto, así que un `launchers.json`
  anterior a las reglas se acomoda solo en el primer arranque.
- **La categoría se crea sola la primera vez que hace falta** (no hay una
  "Juegos" vacía si no hay juegos). Se identifica por un id estable
  (`auto_games`, `auto_store`), así que renombrarla no rompe la regla. Si
  el usuario ya tiene una categoría con ese nombre, **se usa esa** en vez
  de duplicarla.
- **Eliminar una de estas categorías es definitivo**: se anota en
  `dismissed_auto_rules` y la regla no la vuelve a crear. Crear a mano
  una categoría con ese nombre la reactiva.
- **Activar/desactivar**: Configuración → Categorías (checkbox por
  regla, `settings["auto_categories"]`). Al Guardar se aplica al
  instante (`apply_auto_categories()`), sin re-escanear. Desactivar no
  devuelve lo que ya se movió.
- **Qué NO se detecta, y por qué**: categorías "semánticas" (navegadores,
  desarrollo, multimedia...) exigirían una lista de programas que
  siempre queda incompleta. Tampoco hay "Sistema": `shortcut_scanner` ya
  descarta las herramientas de `C:\Windows` antes de que lleguen a
  las reglas.
- **Agregar una regla**: una función `(entry) -> bool` y un `AutoRule`
  en `RULES`; la página de Configuración se arma recorriendo `RULES`.

**API** (`core/launcher_manager.py`): `categories()`, `category_of()`,
`check_category_title()`, `create_category()`, `rename_category()`,
`delete_category()`, `move_category()`, `move_entry_to_category()`, y
`apply_auto_categories()`, y `add_manual_entry(entry, group_id=None)`
(None = conserva la categoría que ya tenía, o la por defecto).

---

## Decisiones de diseño

- **PySide6 (LGPL)** en vez de PyQt6 (GPL), por libertad de
  distribución.
- **El "crecimiento" en hover nunca cambia el tamaño real del widget**:
  el widget siempre reserva el espacio expandido, solo se redibuja más
  grande adentro de ese espacio. Cambiar el tamaño real en cada frame
  recalcularía el layout de toda la lista constantemente, lo cual
  trababa el scroll.
- **`core/paths.py` resuelve todo en absoluto** (basado en dónde vive
  el proyecto o el `.exe`), nunca relativo al directorio de trabajo del
  proceso — la config no se "reseteaba sola" según cómo se lanzara la
  app.
- **Ventana con `WA_TranslucentBackground`**: las zonas "vacías" se
  pintan con alpha=1 real (`QPalette`, nunca QSS) para que Windows no
  las trate como click-through.
- **Recarga en caliente**: guardar en Configuración reconstruye la
  ventana sin reiniciar el proceso, diferido con
  `QTimer.singleShot(0, ...)` para no destruir el widget que disparó la
  acción mientras procesa su propio evento.
- **Reloj de pulso compartido**: un único `QTimer` en `MainWindow`
  anima todos los botones especiales vivos (no uno por instancia), y
  se pausa cuando la ventana está oculta. El mismo timer, cada 6 ticks
  (~270ms), corre además la corrección general de hover pegado (ver
  más abajo).
- **`close_after_launch` existe pero no hace nada**: se pidió
  explícitamente que la ventana nunca se cierre sola al lanzar una app.
  El campo queda en `launchers.json` por compatibilidad con datos
  existentes, pero `MainWindow._on_card_clicked` ignora ese valor a
  propósito.
- **Virtualización solo por encima de un umbral**: reescribir cómo se
  renderiza la lista es tocar el corazón de la UI. Se prefirió dejar el
  camino viejo (3 copias) completamente intacto para el caso común/chico,
  y activar el pool reciclado únicamente donde el problema de
  rendimiento es real. Con categorías el umbral cuenta las apps de
  todas las categorías: si no, repartir 100 apps en categorías
  desactivaría la virtualización justo donde más hace falta.
- **Una categoría es un grupo, y las entradas viven dentro de su
  grupo** (en vez de un campo `category` en cada entrada con los grupos
  derivados al mostrar): reutiliza el esquema que ya existía, un
  `launchers.json` de la v1 no necesita migración, y el orden de las
  categorías es simplemente el orden de `groups`.
- **`_PRESERVED_FIELDS`** (`hidden`, `hover_background`, `favorite`, `category_locked`):
  lista única de lo que el usuario puso sobre una entrada detectada y
  un rescan no puede pisar. Si mañana se agrega otra personalización
  (ej. nombre propio), se agrega acá — es la lección de los tres bugs
  de "se guarda bien, el siguiente arranque lo pisa".
- **Tarjetas cableadas en un solo lugar** (`MainWindow._wire_card`):
  las dos rutas que crean tarjetas (copias y pool) duplicaban el bloque
  de `connect()`; agregar señales nuevas obligaba a tocar ambas.
- **Diálogos que abre una tarjeta se difieren**: "Nueva categoría..."
  abre su diálogo con `QTimer.singleShot(0, ...)`, no dentro del
  `contextMenuEvent` de la tarjeta — un diálogo modal es un event loop
  anidado, y si el escaneo en background termina mientras está abierto
  se reconstruye la lista y se destruye la tarjeta que sigue en la
  pila.

---

## Modelo de datos

`config/launchers.json` (ver `config/launchers.schema.json` para el
ejemplo completo):

```json
{
  "groups": [
    {
      "group_id": "Group1",
      "title": "Programas",
      "launchers": [
        {
          "id": "shortcut_<hash>",
          "name": "Visual Studio Code",
          "type": "shortcut",
          "target": "C:\\...\\Visual Studio Code.lnk",
          "icon": "auto",
          "source": "auto",
          "close_after_launch": true,
          "hidden": false,
          "favorite": false,
          "hover_background": "C:\\...\\fondo.png"
        }
      ]
    }
  ]
}
```

- `type`: `"shortcut"` | `"steam"` | `"uwp"`.
- `source`: `"auto"` (detectado, se puede pisar en el próximo escaneo
  salvo lo protegido explícitamente) | `"manual"` (nunca se toca en
  `refresh()`).
- `groups`: cada uno es una **categoría** (ver [Categorías](#categorías-v2)).
  `group_id` `"Group1"` es la por defecto; las creadas por el usuario
  usan `"cat_<8 hex>"`. Al cargar, `_normalize_data()` garantiza ids
  únicos, título, `launchers` como lista, ninguna entrada repetida
  entre grupos y la presencia de la categoría por defecto.
- `dismissed_auto_rules` (raíz): ids de reglas automáticas cuya categoría
  el usuario eliminó; esas reglas no la recrean.
- `category_locked`: el usuario fijó la app a su categoría; las reglas
  automáticas no la mueven.
- `hidden`, `favorite`, `hover_background`: solo se escriben si el
  usuario los usó — no se agrega un campo con valor por defecto para
  cada entrada, para no ensuciar el archivo.
- El **id es el contrato de estabilidad** de todo el sistema de
  personalización: si cambiara entre escaneos, se perdería la imagen de
  fondo, el estado oculto y la marca de favorita de esa entrada. Por
  eso está normalizado (path en minúsculas, sin `..`/dobles barras)
  para shortcuts, y por qué existe un test dedicado
  (`test_id_de_shortcut_es_estable_ante_variaciones_del_path`).

`config/settings.json` — ver `DEFAULT_SETTINGS` en
`core/config_manager.py` para la lista completa de claves
(`window`, `animation`, `buttons`, `detection`, `auto_categories`, `hotkey_toggle`). Un
archivo de una versión anterior que le falte una clave nueva se
completa automáticamente con los defaults al cargar
(`_merge_with_defaults`), sin perder lo que sí tenía.

> Ejemplo completo (un grupo por categoría, una entrada de cada tipo):
> `config/launchers.schema.json`.

---

## Historial de estabilidad (por qué el código se ve así)

Vale la pena dejar constancia de esto porque explica varias decisiones
que, mirando el código aislado, podrían parecer sobre-ingeniería.

**Persistencia**
- **Los datos del usuario vivían dentro de la carpeta del proyecto, y se
  perdían al actualizar el código.** La imagen de fondo (y favoritas,
  categorías...) se guardaba bien, pero al reemplazar la carpeta del
  proyecto por una copia más nueva, el `config/launchers.json` de esa copia
  pisaba el del usuario. Se detectó en `debug.log`: tras asignar un fondo,
  el siguiente arranque cargaba un archivo con otra cantidad de entradas
  que la que la sesión anterior había guardado (97 → 61, 88 → 61,
  83 → 91; el mismo 61 tres veces = una copia fija restaurada). Ahora
  `core/paths.py` guarda `config/` y `cache/` en `%APPDATA%\SpectrumLauncher`
  y `migrate_legacy_data()` copia lo que hubiera en la carpeta vieja la
  primera vez (copia, no mueve; nunca pisa lo que ya existe en el destino).
  Tests: `test_migracion_*`, `test_reemplazar_la_carpeta_del_proyecto_no_pierde_el_fondo`.
- `LauncherManager._save()`/`config_manager.save_settings()` escriben
  atómico (a un `.tmp` y `os.replace()`), porque antes una interrupción
  a mitad de escritura (kill forzado, corte de luz) dejaba el archivo
  truncado, y **eso** hacía que la app no volviera a abrir nunca más
  (nadie capturaba `json.JSONDecodeError` al cargar). Ahora un archivo
  corrupto se detecta, se guarda una copia (`.corrupt`) para investigar,
  y se arranca con los valores por defecto.
- `LauncherManager` tiene un `threading.Lock` porque el escaneo corre en
  su propio hilo y el usuario puede agregar una app o asignar una
  imagen mientras tanto — sin el lock, ambos hilos podían pisarse la
  escritura del archivo entre sí.

**Hover "pegado"**
Esta clase de bug apareció varias veces, cada vez en un lugar distinto,
porque la causa raíz es la misma en todos: Qt solo actualiza el hover
de un widget cuando el **mouse se mueve de verdad** — si el *contenido*
se mueve bajo un cursor quieto (el salto del scroll infinito, una
reconstrucción de la lista, el reciclado del pool virtualizado), Qt no
entrega el `enter`/`leaveEvent` que corresponde. Se corrigió en capas:
1. `LauncherCard.force_unhover_if_stale()` compara el estado visual de
   una tarjeta contra la posición **real** del cursor
   (`QApplication.widgetAt`), no contra el historial de eventos de Qt.
2. `MainWindow._resync_all_hover_states()` la corre sobre todas las
   tarjetas vivas después de cada scroll y de cada reconstrucción de
   la lista.
3. `MainWindow._maybe_hide_overlay()` (el panel expandido) usa el mismo
   criterio en vez de `QWidget.underMouse()`, que es justamente el
   flag que puede quedar obsoleto.
4. `MainWindow._check_stale_hover()` es la capa final: una red de
   seguridad periódica (cada ~270ms, colgada del timer de pulso de los
   botones) para cualquier causa que no sea scroll ni reconstrucción —
   la ventana pierde el foco un instante, el sistema está ocupado y Qt
   pierde un evento, etc.

**Bugs de la v1 encontrados al construir las categorías (v2)**
- **Las favoritas se perdían en cada arranque.** `refresh()` solo copiaba
  `hidden` y `hover_background` de la versión anterior de una entrada
  detectada; `favorite` quedaba afuera, así que "Marcar como favorita"
  sobre cualquier app detectada (la mayoría) se deshacía en el siguiente
  rescan — el mismo patrón que el bug de la imagen de fondo. Test:
  `test_refresh_preserva_las_favoritas`.
- **Las tarjetas del pool virtualizado tenían 640 px de ancho.** Viven
  fuera de un layout, y un widget sin layout ni tamaño explícito toma el
  default de Qt (640 px): en una ventana de ~340 px, el botón de
  expandir y los mini-botones del lado derecho quedaban fuera de la
  ventana. Solo ocurría con 60+ apps (el desarrollo de esa parte corrió
  en modo offscreen, donde no se nota a simple vista). Ahora cada fila
  se coloca con el ancho actual del contenedor y un filtro de eventos
  la reajusta si cambia. Test: `test_las_tarjetas_del_pool_toman_el_ancho_del_contenedor`.
- **Un `launchers.json` válido pero con forma rara reventaba más tarde**
  (raíz que no es objeto, grupos sin `group_id`, entradas sin `id`, una
  app repetida en dos grupos). Ahora se normaliza al cargar; si la raíz
  no es un objeto se trata como corrupto (copia `.corrupt` + defaults).

**Recursos y concurrencia**
- **"Cerrar" no terminaba el proceso** (la terminal no volvía hasta
  cerrarla). `_on_quit` solo ocultaba la bandeja y liberaba el atajo; un
  escaneo en marcha (PowerShell, hasta 15 s) o un `QThread` vivo mantenían
  el proceso abierto, y Ctrl+C no hacía nada porque Python no recupera el
  control mientras corre el bucle de Qt. Ahora: `MainWindow.shutdown()`
  (idempotente) oculta todo, libera el atajo (y quita su filtro nativo),
  detiene timers y espera a los hilos de fondo con un tope de 1,5 s;
  `main.py` lo conecta a `aboutToQuit` (cubre Cerrar, Ctrl+C/Ctrl+Pausa,
  SIGTERM y cierre de sesión), cierra el guard de instancia única y
  termina el proceso con `os._exit()` — seguro porque todo se escribe al
  instante y de forma atómica. Tests: `test_shutdown_*`, `test_ctrl_c_*`.
- `icon_extractor._hicon_to_pil()` libera explícitamente los 3 handles
  GDI que pide para renderizar cada ícono (antes se filtraban ~3 por
  cada ícono nuevo — la app está pensada para vivir semanas en la
  bandeja).
- `LauncherManager.launch()` nunca propaga una excepción: un target
  roto (app desinstalada desde el último escaneo) devuelve `None` en
  vez de crashear la app entera, y `MainWindow` le avisa al usuario por
  la bandeja.
- `visible_groups()`, `hidden_entries()` y las funciones de categorías
  toman el mismo lock que las escrituras: ahora que `refresh()` reparte
  entradas entre varias listas, una lectura sin lock podía ver una app
  duplicada o ausente a mitad de un rescan.
- Agregar dos apps manuales seguidas antes podía crashear la app
  (`QThread: Destroyed while thread is still running`) porque solo se
  guardaba la referencia al último hilo de resolución de ícono, no a
  todos los que estuvieran corriendo.

---

## Optimización: rendimiento, funcionalidad, responsive y textos

Ronda posterior a categorías/categorización automática, a partir de un
análisis pedido por el usuario sobre el proyecto completo. Cada punto
tiene un test dedicado (ver [Tests](#tests)); los dos de rendimiento y
concurrencia marcados con ⚙ además se probaron con *mutation testing*:
se revirtió el fix a mano, se confirmó que el test nuevo fallaba sin
él, y se volvió a aplicar.

**Rendimiento**
- ⚙ `extract_steam_icon()`/`extract_uwp_icon()` (`core/icon_extractor.py`)
  ahora consultan el PNG ya cacheado **antes** de hacer el trabajo caro
  (listar `appcache/librarycache/<appid>/` de Steam, o parsear
  `AppxManifest.xml` + resolver el asset escalado). Antes ese trabajo
  se repetía en cada `refresh()` aunque el ícono ya estuviera cacheado.
- `LauncherManager.refresh()` ya no lee el registro de Windows
  (`steam_detector.get_steam_path()`) dos veces en el mismo escaneo —
  se resuelve una sola vez y se reutiliza tanto para
  `scan_steam_library()` como para la extracción de íconos.
- ⚙ `MainWindow._all_live_cards()` recorría el árbol de widgets con
  `findChildren(LauncherCard)` en **cada** llamada, y se llama desde el
  chequeo periódico de "hover fantasma" (~270ms, todo el tiempo que la
  ventana está visible). Ahora se mantiene una lista explícita
  (`self._live_cards`), poblada por `_wire_card()` en las dos rutas de
  construcción de tarjetas (pool virtualizado y copias de siempre).

**Concurrencia**
- ⚙ `LauncherManager.is_favorite()` y `.launch()` leían `self.data` sin
  tomar `self._lock`, a diferencia de `categories()`/`visible_groups()`/
  etc. — una condición de carrera real contra `refresh()` corriendo en
  su propio hilo. Ahora toman el lock; en `launch()` solo para la
  búsqueda de la entrada, soltándolo antes de `os.startfile()` (lanzar
  un proceso externo no tiene por qué bloquear un `refresh()`
  concurrente).

**Funcionalidad**
- El ancho de la ventana (`window.width`) tiene ahora un control en
  Configuración → General (slider 260–600px) y se aplica en caliente al
  guardar, sin reiniciar — antes solo se podía cambiar editando
  `settings.json` a mano, y ni así tenía efecto sin reiniciar el
  programa.
- La página de ayuda "Atajos" mostraba el atajo global hardcodeado como
  `Ctrl+Alt+Espacio`, aunque el usuario lo hubiera cambiado en el combo
  de arriba. Ahora se arma con un template que toma la combinación
  realmente seleccionada, y se actualiza en vivo mientras se cambia el
  combo (incluso antes de guardar).
- "Buscar de nuevo ahora" (Configuración → Detección) bloqueaba todo el
  diálogo mientras duraba el escaneo (varios segundos en frío). Ahora
  reusa el mismo `QThread` en background que el escaneo automático al
  iniciar (`core/scan_worker.py`); Guardar/Cancelar se deshabilitan
  mientras corre para no cerrar el diálogo con el hilo todavía vivo.

**Codificación de caracteres (apps de Microsoft Store con nombres no-ASCII)**
- Algunas apps de Microsoft Store con nombres con tildes, eñes, u otros
  caracteres fuera de ASCII (p. ej. "Música y vídeos", "Configuración")
  aparecían con el nombre roto, o directamente no aparecían en la lista.
  Causa: `core/uwp_detector.py` llama a PowerShell (`Get-StartApps`) vía
  `subprocess.run(..., text=True)` sin `encoding=` explícito — eso hace
  que Python decodifique la salida con `locale.getpreferredencoding()`
  (la codificación ANSI/OEM del sistema), que no necesariamente coincide
  con la que `powershell.exe` usó al escribir en el pipe redirigido; con
  una app cuyo nombre cae fuera de esa codificación, el resultado llega
  corrupto o la respuesta deja de poder interpretarse como JSON (la
  detección de esa app se pierde en silencio). Se corrigió forzando
  UTF-16 (la codificación nativa de cualquier string de .NET/Windows,
  sin conversión de por medio) en los dos lados: el script de PowerShell
  fija `[Console]::OutputEncoding = [System.Text.Encoding]::Unicode` al
  principio, y Python captura los bytes crudos (sin `text=True`) y los
  decodifica explícitamente como `"utf-16"`, con `errors="replace"` como
  red de seguridad para que un carácter puntual no tire abajo toda la
  detección de Microsoft Store.

**Responsive / textos**
- Tooltip de la tarjeta: cuando el nombre se truncaba, su propio
  tooltip (el nombre completo) tapaba al tooltip de la ruta del
  programa (opción "Mostrar tooltip con la ruta"). Ahora se combinan en
  vez de pisarse.
- Los títulos de categoría largos ahora se eliden con "…" contra el
  ancho disponible, tanto en la lista chica (`_build_group_stack`) como
  en la lista virtualizada (headers de `virtual_card_list.py`) y en el
  panel expandido (`expand_overlay.py`) — antes se recortaban a lo
  bruto contra el borde de la ventana.
- Las reglas de categorización automática (Configuración → Categorías)
  mostraban título + descripción pegados en una sola línea de
  `QCheckBox` (hasta ~110 caracteres, sin wrap), cortada a lo bruto
  contra el ancho mínimo del diálogo. Ahora el checkbox solo lleva el
  título y la descripción va debajo en un `QLabel` con `wordWrap`.

---

## Dependencias

Ver `requirements.txt`, con el razonamiento de cada piso de versión
comentado ahí mismo. Resumen:

| Paquete   | Piso     | Motivo |
|-----------|----------|--------|
| PySide6   | >=6.8    | Sin CVEs conocidos; se sube por arreglos de crashes relevantes (`QCoreApplication.processEvents()`, que el rescan manual llama). |
| pywin32   | >=311    | El único CVE conocido (integer overflow en ACLs) afecta a versiones anteriores a la 301; se sube igual por soporte de Python más nuevo. |
| vdf       | >=3.4    | Sin CVEs conocidos. |
| Pillow    | >=12.3.0 | El piso anterior (`>=10.0`, sin techo) permitía instalar versiones con varios CVEs de corrupción de memoria y DoS (algunos con RCE potencial vía PSD/EPS crafteados). 12.3.0 es la primera que los corrige todos. Exposición real baja — el proyecto solo abre imágenes que el propio usuario elige o íconos de programas ya instalados —, pero no había motivo para quedarse en una versión vulnerable. |

---

## Tests

89 tests, corren en cualquier sistema operativo (`tests/conftest.py`
stubea `winreg`/`win32gui`/`win32com`/`pythoncom` para eso):

```
python -m pytest tests/ -v
```

**`tests/test_core.py` (60, sin UI)** — persistencia de imagen de fondo
entre reinicios, preservación de apps ocultas y favoritas, no pérdida de
personalización al re-agregar una app manual, recuperación ante JSON
corrupto (tanto `launchers.json` como `settings.json`, incluyendo JSON
válido de forma rara), escritura atómica sin residuos, merge de settings
con los defaults, no-mutación de los defaults globales, `launch()` sin
propagar excepciones, orden alfabético con acentos/eñes, favoritas
primero, filtrado de ocultas, carreras reales entre `refresh()` y
`add_manual_entry()` / `move_entry_to_category()`, estabilidad del id de
un shortcut, y las **categorías**: refresh respeta la categoría de cada
app, apps nuevas a la por defecto, mover/persistir, eliminar (las apps
vuelven), validación y renombrado de nombres, reordenar, re-agregar una
manual sin duplicarla, orden por categoría, y compatibilidad con un
`launchers.json` de la v1. Y la **categorización automática**: Steam a
"Juegos" (creada solo si hace falta), retroactividad sobre instalaciones
anteriores, respeto de lo movido a mano, renombrar / eliminar (no se
recrea) / recrear a mano / adoptar una categoría "Juegos" existente,
launchers y juegos de otras tiendas por ruta, la regla de Microsoft Store
apagada por defecto, `apply_auto_categories` idempotente, (ronda de
optimización) que `is_favorite()`/`launch()` esperan el lock en vez de
leer `self.data` sin él (probado de forma determinística: se toma el
lock a mano, se arranca un hilo, se verifica que queda bloqueado), y que
`scan_uwp_apps()` decodifica correctamente nombres con tildes/eñes desde
los bytes crudos (UTF-16) que devolvería `powershell.exe`, en vez de
asumir una codificación ANSI/OEM que los corrompe.

**`tests/test_ui.py` (29, offscreen)** — el pool virtualizado (ancho de
las tarjetas, cobertura del viewport con varias categorías, posición de
los títulos, tamaño acotado), cuándo se activa la virtualización con
categorías, títulos de una lista chica, cablear el menú contextual, la
página Configuración → Categorías (crear, renombrar, ordenar, eliminar
con y sin confirmación, nombre repetido, y guardar/aplicar las reglas
automáticas), y (ronda de optimización) que `_all_live_cards()` no
recorre el árbol de widgets y se reinicia al reconstruir la lista, que
el tooltip de la ruta no queda tapado por el del nombre truncado (con y
sin la opción activada), que un título de categoría largo se elide
tanto en la lista chica como en la virtualizada, que el rescan corre en
background sin bloquear el diálogo (y que cerrarlo a mitad de un rescan
no lo cierra), y que el checkbox de una regla automática no lleva la
descripción pegada. Se saltea solo si PySide6 no está instalado. No
cubre el menú contextual real (los popups no se automatizan bien), la
animación de hover, ni nada específico de Windows.

---

## Limitaciones conocidas

- **La categorización automática es solo por origen y ruta**: juegos y
  Microsoft Store. Un juego de Microsoft Store/Xbox no se reconoce como
  juego, y programas "de desarrollo", "multimedia", etc. no se agrupan
  solos. Tampoco hay arrastrar y soltar ni categorías plegables.
- **Con los botones especiales "Dentro de la lista" no se virtualiza**,
  aunque haya cientos de apps: vuelve al camino de 3 copias.
- **El pool virtualizado se reconstruye entero en cada
  `_refresh_layout()`**, aunque la lista siga estando virtualizada
  antes y después del cambio — sigue siendo muchísimo mejor que
  reconstruir toda la lista real, pero es trabajo evitable.
- **El resultado de PowerShell (detección de Microsoft Store) no se
  cachea entre escaneos muy seguidos** — tocar "Buscar de nuevo ahora"
  dos veces seguidas repite ese costo (1-3s típicos) sin que haya
  cambiado nada del lado de Windows.
- **Tests de UI acotados** (ver sección Tests): no hay cobertura del menú contextual real ni de la animación de hover.
- No validado en una máquina Windows real de punta a punta desde la
  virtualización en adelante (incluye todo lo de categorías) — todo el desarrollo posterior corrió
  contra Qt en modo *offscreen* (sin esto no había forma de iterar).
  Recomendable un smoke test visual con una lista grande (100+ apps)
  antes de distribuir.

---

## Ideas para v2

En orden aproximado de valor esperado (categorías ya está hecho):

1. **Más reglas automáticas** en `auto_categories.py`, por lista de
   ejecutables conocidos (navegadores, desarrollo, multimedia,
   comunicación...): mejor esfuerzo, hay que aceptar que queda incompleta.
2. **Seguir partiendo `main_window.py`** — candidatos claros:
   `tray_manager.py` (bandeja, visibilidad, fade), `list_builder.py`
   (las dos variantes de construcción de lista), `scroll_controller.py`
   (infinito + virtual + resync de hover).
3. **Reusar el pool virtualizado entre reconstrucciones** en vez de
   recrearlo siempre.
4. **Cachear el resultado de PowerShell** con un timestamp simple.
5. **Renombrar una app detectada** sin tener que re-agregarla a mano
   (sumar `name` a `_PRESERVED_FIELDS`).
6. **"Abrir ubicación del archivo" / "Ejecutar como administrador"**
   en el menú contextual.
7. **Categorías plegables** y/o arrastrar una tarjeta a otra categoría.
8. Ampliar los tests de UI (menú contextual, hover).
