# SPECTRUM Launcher

Lanzador de aplicaciones para Windows 10/11. Es un panel flotante, sin bordes y translúcido, que detecta solo los programas instalados (Steam, accesos directos y Microsoft Store), los muestra como una lista de tarjetas animadas y los abre con un clic o desde el teclado. Vive en la bandeja del sistema y se muestra u oculta con un atajo global.

Está escrito en Python con PySide6 (Qt 6). No usa red ni servicios externos: todo lo que guarda queda en la carpeta de datos del usuario.

Este documento es la referencia única del proyecto: qué hace la app, cómo está organizada y qué hay que respetar al modificarla.

---

## 1. Qué hace

### Detección de apps

- **Steam**: los juegos instalados en todas las bibliotecas. Se abren con `steam://rungameid/<appid>`.
- **Accesos directos**: los `.lnk` del Menú Inicio y del Escritorio, tanto del usuario como de todos los usuarios. Las carpetas se le preguntan a Windows, así que funciona con el Escritorio redirigido a OneDrive.
- **Microsoft Store (UWP)**: las apps que aparecen en el Menú Inicio, vía PowerShell.
- Cada fuente se puede desactivar en Configuración. El escaneo corre al iniciar (opcional) y a pedido con "Buscar de nuevo ahora".
- Se descartan desinstaladores, ayudas, enlaces web y las herramientas del propio Windows.
- Dos accesos al mismo ejecutable con argumentos distintos (apps web de Chrome/Edge, herramientas de Python o Java) aparecen como apps separadas.

### Lista

- Tarjetas con icono y nombre, agrupadas por categoría, con animación al pasar el mouse (crecimiento, color, desplazamiento).
- Scroll sin barras. Si la lista no entra en pantalla, el scroll es en bucle: al llegar al final continúa desde el principio.
- Orden configurable: favoritas primero, alfabético o por orden de detección. El orden alfabético ignora acentos.
- Las favoritas llevan una estrella a la derecha del nombre.
- Panel ampliado: al pasar el mouse por la flecha de una tarjeta se despliega fuera de la ventana un panel con la imagen de fondo de la app, su icono, su nombre y de dónde sale. Un clic en el panel abre la app.

### Búsqueda y teclado

- Al mostrarse la ventana el buscador ya tiene el foco: el flujo es **atajo → escribir → Enter**.
- La búsqueda ignora mayúsculas y acentos, acepta varias palabras en cualquier orden, siglas (`vsc` encuentra "Visual Studio Code"), el nombre del ejecutable (`winword` encuentra "Word") y, como último recurso, letras salteadas.
- Los resultados se ordenan por relevancia y el mejor queda seleccionado.
- **Enter** abre la app seleccionada. **Flechas** y **Re Pág / Av Pág** cambian la selección, también sin búsqueda.
- **Escape** limpia la búsqueda; sin búsqueda, oculta la ventana.

### Acciones sobre una app

Clic derecho sobre la tarjeta, o los mini-botones que aparecen al pasar el mouse:

- Abrir (clic). Un doble clic no la abre dos veces.
- Marcar o quitar como favorita.
- Mover a una categoría, o crear una nueva en el momento.
- Asignar o quitar una imagen de fondo, que se revela tras un momento de hover.
- Quitar de la lista (se oculta, no se borra; se restaura desde Configuración).
- Agregar a mano cualquier `.exe` con el botón "Agregar app".

Cada acción se confirma con un **aviso** breve dentro de la ventana ("Abriendo Blender…", "Movida a Juegos"). Quitar una app ofrece **Deshacer** en el propio aviso. Los errores que el usuario tiene que ver aunque la ventana esté oculta salen como globo de la bandeja.

### Categorías

- Se crean, renombran, reordenan y eliminan desde Configuración. La categoría por defecto ("Programas") se puede renombrar pero no eliminar.
- Al eliminar una categoría sus apps vuelven a la categoría por defecto.
- Reglas automáticas opcionales: **Juegos** (Steam y las bibliotecas o launchers de Epic, GOG, Riot, Battle.net, EA y Ubisoft; activa por defecto) y **Microsoft Store** (apagada por defecto). Una regla nunca mueve una app que el usuario ya movió a mano.

### Ventana, bandeja y atajo

- Sin botón en la barra de tareas ni en Alt+Tab. Opcionalmente siempre visible.
- Se arrastra desde cualquier parte y recuerda su posición.
- Icono en la bandeja con menú: Mostrar/Ocultar, Configuración, Abrir carpeta de datos, Cerrar.
- Cerrar la ventana solo la oculta. El programa termina con "Cerrar" en la bandeja.
- Atajo global para mostrar/ocultar (por defecto Ctrl+Alt+Espacio, a elegir entre cinco combinaciones). Si el atajo ya lo usa otro programa, se avisa.
- Instancia única: ejecutar el programa por segunda vez trae al frente la ventana que ya estaba abierta.

### Configuración

Se abre con el botón, con Ctrl+Shift+S o desde la bandeja. Los cambios se aplican al guardar, sin reiniciar.

| Página | Qué se ajusta |
|---|---|
| General | Opacidad, ancho, siempre visible, tooltip con la ruta, orden de la lista, alto de las tarjetas |
| Detección | Fuentes activas, buscar al iniciar, re-escaneo manual |
| Animación | Duración, crecimiento, curva, velocidad, desplazamiento, lado de la flecha, alto del panel ampliado. Con vista previa |
| Botones | "Agregar app" y "Configuración": fuera de la lista, dentro o ocultos |
| Categorías | Gestión de categorías y reglas automáticas |
| Apps ocultas | Restaurar las apps quitadas de la lista |
| Atajos | Atajo global y ayuda de teclado |

---

## 2. Puesta en marcha

Requiere Windows 10/11 y una versión de Python compatible con PySide6 6.8 (3.9 o superior).

```bat
pip install -r requirements.txt
python main.py
```

Tests (los de `core/` corren también en Linux y macOS; los de `ui/` necesitan PySide6 y se saltean solos si no está):

```bat
pip install pytest
python -m pytest tests/ -v
```

Empaquetado a `.exe` (detalles y opciones en la cabecera de `main.spec`):

```bat
pip install pyinstaller
pyinstaller --noconfirm main.spec
```

El resultado es la carpeta `dist\SpectrumLauncher\`, que se distribuye entera.

---

## 3. Estructura

```
main.py                    Punto de entrada: instancia única, migración de datos, ventana, cierre
main.spec                  Empaquetado con PyInstaller
requirements.txt           Dependencias y motivo de cada piso de versión

core/                      Lógica sin interfaz. No importa nada de ui/
  paths.py                 Rutas absolutas y carpeta de datos del usuario
  config_manager.py        settings.json: valores por defecto, validación, guardado atómico
  launcher_manager.py      launchers.json: fusión de escaneos, categorías, personalización, lanzar
  search.py                Motor de búsqueda (lógica pura)
  auto_categories.py       Reglas de categorización automática (lógica pura)
  steam_detector.py        Juegos de Steam (registro + archivos VDF)
  shortcut_scanner.py      Accesos directos .lnk
  uwp_detector.py          Apps de Microsoft Store (PowerShell)
  icon_extractor.py        Extracción y caché de iconos
  scan_worker.py           QThread del escaneo y de la extracción de iconos de apps manuales
  single_instance.py       Guard de instancia única (QLocalServer)
  debug_log.py             Log de diagnóstico

ui/                        Interfaz (PySide6)
  main_window.py           Ventana principal: lista, búsqueda, teclado, acciones, bandeja, avisos
  launcher_card.py         Tarjeta de una app: animaciones, menú contextual, mini-botones
  virtual_card_list.py     Pool reciclado de tarjetas para listas grandes
  toast.py                 Aviso breve dentro de la ventana, con acción opcional
  expand_overlay.py        Panel ampliado de una tarjeta
  special_button.py        Botones "Agregar app" y "Configuración"
  settings_window.py       Diálogo de Configuración
  add_app_dialog.py        Diálogo "Agregar app"
  category_dialogs.py      Pedir y validar el nombre de una categoría
  global_hotkey.py         Atajo global (RegisterHotKey de Windows)
  app_icon.py              Icono de la app, dibujado por código
  text_utils.py            Truncado de textos con "…"

tests/
  conftest.py              Stubs de los módulos de Windows, para correr core/ en cualquier sistema
  test_core.py             Persistencia, fusión, orden, categorías, reglas, concurrencia, rutas
  test_search.py           Motor de búsqueda
  test_robustness.py       Fuentes que fallan, apps que vuelven, accesos con argumentos, caché, settings
  test_ui.py               Tarjetas, pool, modos de lista, búsqueda, avisos, Configuración, cierre

tools/                     Scripts sueltos: generar el .ico y diagnosticar la detección de Steam
config/                    Solo una plantilla de referencia (launchers.schema.json). No guarda datos
assets/icons/spectrum.ico  Icono del .exe
```

---

## 4. Datos del usuario

Todo vive **fuera** del proyecto, en `%APPDATA%\SpectrumLauncher\` (se abre desde la bandeja con "Abrir carpeta de datos"). Así se puede reemplazar la carpeta del código sin perder nada.

| Archivo | Contenido |
|---|---|
| `config\launchers.json` | Apps, categorías y personalización |
| `config\settings.json` | Ajustes |
| `config\debug.log` | Registro de diagnóstico (se reinicia al pasar de 200 KB) |
| `cache\extracted_icons\` | Iconos ya extraídos, en PNG |

- La variable de entorno `SPECTRUM_DATA_DIR` cambia la carpeta de datos (modo portable y pruebas).
- Si en `config\` del proyecto hay un `launchers.json` o `settings.json` de una versión antigua, se copian a la carpeta de datos la primera vez, solo si allí todavía no existen.
- Un archivo corrupto se aparta como `.corrupt` y la app arranca con valores por defecto.

### `launchers.json`

```json
{
  "groups": [
    {"group_id": "Group1", "title": "Programas", "launchers": [ ...entradas... ]},
    {"group_id": "cat_1a2b3c4d", "title": "Juegos", "launchers": [ ... ]}
  ],
  "dismissed_auto_rules": [],
  "remembered": {"steam_440": {"favorite": true, "group_id": "cat_1a2b3c4d"}}
}
```

Cada grupo es una categoría; `Group1` es la categoría por defecto y siempre existe.

Campos de una entrada:

| Campo | Significado |
|---|---|
| `id` | Identidad estable entre escaneos: `steam_<appid>`, `shortcut_<hash>`, `uwp_<hash>`, `manual_<hash>` |
| `name` | Nombre visible |
| `type` | `steam`, `shortcut` o `uwp` |
| `target` | Qué es la app: el `.exe`, la URL `steam://` o la ruta `shell:AppsFolder\...` |
| `launch` | Solo accesos directos detectados: el `.lnk` que se ejecuta |
| `icon` | Ruta al PNG en caché, o `"auto"` (icono genérico) |
| `source` | `auto` (detectada) o `manual` (agregada por el usuario) |
| `favorite`, `hidden`, `hover_background`, `category_locked` | Personalización. Solo existen si el usuario los usó |

- `remembered` guarda la personalización de apps detectadas que dejaron de aparecer, para devolvérsela si vuelven. Tiene tope y solo existe si hay algo que recordar.
- `dismissed_auto_rules` lista las reglas automáticas cuya categoría el usuario eliminó, para no volver a crearla.
- `close_after_launch` se conserva por compatibilidad y no tiene efecto: la ventana nunca se cierra sola al abrir una app.
- Las imágenes de fondo no se copian: se guarda su ruta.

---

## 5. Cómo funciona por dentro

### Arranque

1. `main.py` comprueba la instancia única, migra datos antiguos y carga `settings.json` y `launchers.json`.
2. La ventana se muestra de inmediato con lo que había guardado.
3. El escaneo corre en un `QThread`. Al terminar, la lista solo se redibuja si algo cambió.

### Escaneo y fusión (`LauncherManager.refresh`)

1. Los detectores y la extracción de iconos (8 hilos) corren **fuera** del lock.
2. Con el lock tomado se fusiona lo detectado con lo existente:
   - Las entradas manuales no se tocan.
   - Las detectadas conservan su personalización y su categoría.
   - Si una fuente **falló** (devolvió `None` o lanzó una excepción), sus apps se quedan como estaban.
   - Si una app dejó de detectarse, sale de la lista y su personalización pasa a `remembered`.
   - Se aplican las reglas automáticas a lo que sigue en la categoría por defecto.
3. Se escribe el archivo solo si hubo cambios y se devuelve un resumen (`changed`, `added`, `removed`, `failed`).

### Modos de la lista (`MainWindow._list_mode`)

| Modo | Cuándo | Cómo |
|---|---|---|
| `loop` | La lista no entra en pantalla y tiene menos de 60 apps | 3 copias reales; al llegar a un extremo se salta a la copia del medio |
| `single` | La lista entra en pantalla, o son pocos resultados de búsqueda | Una copia, scroll normal |
| `virtual` | 60 apps o más, o 60 resultados o más | Pool reciclado de ~20 tarjetas, scroll normal |
| `empty` | Nada que mostrar | Un mensaje |

En modo `virtual`, mientras no cambie la configuración visual, el pool se reutiliza: buscar o marcar una favorita solo le pasa datos nuevos, no reconstruye widgets.

### Iconos

- Programas: se extraen con las APIs de Windows al tamaño de icono del sistema (32 px al 100 %, 48 px al 150 %…).
- Steam y Microsoft Store: se toma la imagen que ya existe en disco y se guarda a 64 px.
- La caché se consulta antes de extraer y cada PNG se escribe de forma atómica. Tras cada escaneo se borran los PNG que ya no usa ninguna app (si tienen más de una hora).

---

## 6. Puntos importantes al trabajar en el proyecto

### Datos

- **Un escaneo nunca pisa lo que puso el usuario.** Toda personalización nueva de una entrada (por ejemplo, un nombre propio) se agrega a `_PRESERVED_FIELDS` en `launcher_manager.py`. Con eso queda protegida en `refresh()`, al re-agregar a mano y en `remembered`.
- **Un detector que no pudo hacer su trabajo devuelve `None` o lanza una excepción; nunca `[]`.** Una lista vacía significa "no hay apps" y borra las de esa fuente.
- **El `id` de una entrada no puede cambiar entre escaneos.** Toda la personalización cuelga de él. Si hay que cambiar cómo se calcula, el detector debe emitir también `legacy_id` para que `refresh()` traspase lo que había.
- **Todo acceso a `LauncherManager.data` va dentro de `self._lock`.** El escaneo corre en otro hilo. Los métodos `_unlocked` se llaman con el lock ya tomado; el lock no es reentrante.
- **Nada lento dentro del lock** (PowerShell, disco, abrir procesos).
- **Guardado atómico siempre**: escribir a un temporal y `os.replace()`. Vale para los JSON y para la caché de iconos.
- **Rutas absolutas desde `core/paths.py`.** Nunca relativas al directorio de trabajo.
- **`core/` no importa `ui/`.** La lógica que se pueda escribir sin Qt va en `core/` y se testea ahí.
- Los datos de trabajo de un escaneo (`icon_location`, `install_location`, `legacy_id`) se descartan antes de guardar.

### Interfaz

- **Nunca reconstruir la lista ni abrir un diálogo dentro de la señal de una tarjeta o de un botón.** Se difiere con `QTimer.singleShot(0, ...)`: la reconstrucción destruye el widget que emitió la señal, que todavía está en la pila de llamadas.
- **Los diálogos los abre `MainWindow`, no la tarjeta.** Un diálogo es un bucle de eventos anidado y la tarjeta puede destruirse mientras está abierto.
- **Un diálogo con padre se destruye a mano** (`deleteLater()`) después de `exec()`. Si no, vive hasta cerrar el programa.
- **Una tarjeta se conecta a la ventana solo en `MainWindow._wire_card`.** Una señal nueva de `LauncherCard` se conecta ahí y sirve para los tres modos de lista.
- **`LauncherCard.update_entry()` debe reiniciar todo el estado de la tarjeta.** El pool la reutiliza para otra app; cualquier estado nuevo (como `_selected`) se limpia ahí.
- **El hover no se confía a los eventos de Qt.** Cuando el contenido se mueve bajo un cursor quieto no llegan `enter`/`leave`. Después de cualquier cambio de contenido se llama a `_resync_all_hover_states`.
- **El crecimiento en hover es solo visual.** La tarjeta reserva siempre el alto expandido; cambiar su tamaño real recalcularía el layout de toda la lista en cada frame.
- **Las zonas vacías de la ventana se pintan con alfa 1**, no 0. Windows deja pasar los clics por los píxeles totalmente transparentes.
- **Toda acción del usuario termina en un aviso** (`MainWindow._notify`). Si la acción se puede deshacer, el aviso lo ofrece.
- Los textos visibles van en español con su ortografía completa.

### Cierre

- `MainWindow.shutdown()` es idempotente y espera a los hilos de fondo como máximo 1,5 s. Después `main.py` termina el proceso con `os._exit`. Es seguro porque cada cambio del usuario ya está en disco.
- Los `QThread` en curso se guardan en atributos de la ventana (`_scan_thread`, `_icon_resolve_jobs`). Un `QThread` sin referencia en Python se destruye mientras corre y tira la app.

### Verificación de un cambio

1. `python -m pytest tests/` en Windows, con PySide6 instalado.
2. Lo que dependa de APIs de Windows se prueba a mano, porque los tests usan stubs: extracción de iconos, lectura de `.lnk`, PowerShell, registro de Steam, atajo global y bandeja.
3. Probar con escalado de pantalla al 100 % y al 150 %, y con una lista corta (menos de 8 apps) y una larga (más de 60).
4. Si algo falla, `debug.log` en la carpeta de datos registra cada escaneo, cada error al abrir una app y el cierre.

---

## 7. Límites conocidos

- Solo Windows. Fuera de Windows el código importa (para los tests) pero no detecta ni lanza nada.
- Juegos de Epic, GOG y otras tiendas solo aparecen si tienen un acceso directo `.lnk`; los accesos `.url` no se leen.
- La ventana ocupa siempre el alto disponible de la pantalla; con pocas apps, la zona vacía sigue recibiendo los clics.
- Las apps manuales no se pueden renombrar ni editar: hay que quitarlas y agregarlas de nuevo.
- No hay opción de iniciar con Windows ni de arrancar oculta.
- Si se mueve o borra una imagen de fondo, la app pierde su fondo (se guarda la ruta, no una copia).
- Los iconos en caché no se actualizan si un programa cambia su icono; borrar `cache\extracted_icons\` los regenera.
