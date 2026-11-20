# SPECTRUM Launcher — Qué hace el proyecto

## Resumen

SPECTRUM Launcher es un **lanzador de aplicaciones y juegos para Windows**. Es un panel flotante, sin bordes, que vive en la bandeja del sistema y se muestra u oculta con un atajo de teclado global. Muestra una lista de todo lo que tienes instalado y lo abre con un clic.

Nació como una skin de Rainmeter y fue portado a una aplicación nativa en **Python + PySide6 (Qt)**.

Su idea central: **no tienes que armar la lista a mano**. El programa detecta tus apps solo, las agrupa en categorías y deja que las personalices (imagen de fondo, favoritas, orden, categorías propias) sin que un nuevo escaneo te borre nada.

---

## 1. Qué ve y qué puede hacer el usuario

### 1.1 Un panel que aparece cuando lo necesitas
- Ventana flotante, sin bordes y con fondo translúcido (opacidad configurable).
- No aparece en la barra de tareas: vive como icono en la **bandeja del sistema**.
- **Atajo global** (por defecto `Ctrl+Alt+Espacio`) para mostrar u ocultar la ventana desde cualquier programa, tenga o no el foco. Es editable y se aplica sin reiniciar.
- El menú de la bandeja también tiene **Abrir carpeta de datos**, que abre `%APPDATA%\SpectrumLauncher` en el Explorador.
- Cerrar la ventana o pulsar `Escape` solo la **oculta**. La única forma de cerrar el programa del todo es **"Cerrar"** en el menú de la bandeja.
- La ventana **nunca se cierra sola al lanzar una app**: se queda abierta para que lances varias seguidas.
- Opción de "siempre visible" (encima de las demás ventanas) y ancho ajustable (260–600 px).

### 1.2 Lista de apps detectada automáticamente
Tres fuentes, cada una activable o desactivable por separado en *Configuración → Detección*:

| Fuente | Qué detecta | Cómo |
|---|---|---|
| **Steam** | Todos los juegos instalados, en todas tus bibliotecas (no solo la de por defecto) | Lee `libraryfolders.vdf` y cada `appmanifest_*.acf` |
| **Accesos directos** | Programas del Menú Inicio (usuario y todos los usuarios) y del Escritorio | Recorre los `.lnk` y los resuelve con `WScript.Shell` |
| **Microsoft Store (UWP)** | Apps de la tienda, que no tienen `.lnk` normal | PowerShell (`Get-StartApps` + `Get-AppxPackage`); se lanzan con `shell:AppsFolder\...` |

Detalles que importan:
- Los **iconos** se extraen de cada app (ejecutable, logo del paquete UWP o caché de Steam) y se guardan en caché. La extracción corre en paralelo (8 hilos).
- Las apps de la Store con nombres tipo `ms-resource:...` se resuelven a un nombre legible. Los nombres con tildes y eñes se leen correctamente (UTF-16).
- Las herramientas internas de `C:\Windows` se descartan para no llenar la lista de ruido.
- El escaneo corre en un **hilo aparte**: la ventana aparece al instante con lo guardado de la vez anterior, y se actualiza cuando termina el escaneo.

### 1.3 Agregar apps a mano
El botón **"Agregar app"** abre un diálogo para añadir cualquier ejecutable. Valida campos vacíos, avisa si la ruta no existe (con opción de continuar) y permite elegir categoría. El icono se resuelve en segundo plano, sin trabar la ventana. Las apps agregadas a mano **nunca se tocan** en un rescan.

### 1.4 Categorías
Cada categoría es un bloque con su propio título dentro de la lista.

- **Mover una app:** clic derecho → *Mover a categoría* (o *Nueva categoría...*).
- **Gestionar categorías:** *Configuración → Categorías* permite crear, renombrar, reordenar y eliminar. Eliminar una categoría **nunca borra apps**: pasan a la categoría por defecto ("Programas").
- **Categorización automática:** las apps recién detectadas se mandan solas a una categoría según reglas:
  - **Juegos:** juegos de Steam, launchers de juegos (Steam, Epic, GOG, Battle.net, Ubisoft, EA, Riot, itch) y accesos directos cuyo ejecutable esté en carpetas típicas de tiendas de juegos.
  - **Microsoft Store:** apps UWP (desactivada por defecto).
- Si mueves una app a mano, queda **fijada** (`category_locked`) y las reglas ya no la tocan.
- Si eliminas una categoría automática, la regla no la vuelve a crear.

### 1.5 Personalización de cada tarjeta
Clic derecho sobre una tarjeta:

- **Marcar como favorita:** sube arriba dentro de su categoría.
- **Quitar de la lista:** no la borra, la marca como oculta. Se restaura desde *Configuración → Apps ocultas*.
- **Mover a categoría.**
- **Asignar o quitar imagen de fondo:** tras ~2 segundos con el mouse encima, la imagen se revela con una animación propia.

Además, un botón de **flecha** (aparece al pasar el mouse) abre un panel flotante más grande con la imagen de fondo ampliada, que se desliza desde el borde de la ventana.

### 1.6 Orden
Configurable en *Configuración → General*:
- **Favoritas primero, luego alfabético** (por defecto)
- **Alfabético**
- **Orden de detección**

El orden alfabético normaliza acentos y eñes (`ámbar` va antes que `Blender`). Se aplica **por separado dentro de cada categoría**.

### 1.7 Búsqueda
Caja de texto sobre la lista que filtra por nombre, con debounce de 140 ms.

### 1.8 Animaciones
- Al pasar el mouse, la tarjeta crece, cambia de color, puede deslizarse horizontalmente y da un flash breve al hacer clic.
- **8 curvas de easing** a elegir, con vista previa en vivo en Configuración.
- Los botones especiales ("Agregar app", "Configuración") tienen un pulso continuo.

### 1.9 Panel de Configuración
Navegación lateral con las secciones: **General, Detección, Animación, Botones, Categorías, Apps ocultas y Atajos**. Incluye el tamaño de tarjeta (el icono y la fuente escalan con él), orden, opacidad, tooltips (con ruta del programa opcional), reescaneo manual en segundo plano, ubicación de los botones especiales y el atajo global. Guardar aplica los cambios **en caliente**, sin reiniciar.

### 1.10 Instancia única
Solo puede haber una copia corriendo. Si abres el programa otra vez, la copia nueva le avisa a la que ya estaba para que se muestre y se cierra.

---

## 2. Cómo maneja los datos

### 2.1 Dónde se guardan
Los datos del usuario viven **fuera de la carpeta del código**:

```
%APPDATA%\SpectrumLauncher\
├── config\
│   ├── launchers.json   # apps detectadas + manuales, categorías, personalización
│   ├── settings.json    # ventana, animación, detección, reglas, orden, atajo
│   └── debug.log        # registro de diagnóstico
└── cache\
    └── extracted_icons\ # iconos ya extraídos
```

Así puedes reemplazar o actualizar el código sin perder imágenes de fondo, favoritas ni categorías. La primera vez, si había una carpeta `config/` junto al proyecto, se copia automáticamente (sin pisar lo que ya exista en el destino). Se puede cambiar la ubicación con la variable de entorno `SPECTRUM_DATA_DIR`.

### 2.2 Estructura de `launchers.json`
Cada **categoría es un grupo** (`groups[]`) y cada app vive dentro de su grupo:

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
          "hidden": false,
          "favorite": false,
          "hover_background": "C:\\...\\fondo.png"
        }
      ]
    }
  ],
  "dismissed_auto_rules": []
}
```

- `type`: `shortcut`, `steam` o `uwp`.
- `source`: `auto` (detectada) o `manual` (agregada por el usuario).
- El **`id` es el contrato de estabilidad** de toda la personalización: se calcula con el path normalizado (minúsculas, sin `..` ni dobles barras), para que sea el mismo entre escaneos. Si cambiara, se perdería el fondo, el estado oculto y la marca de favorita.

### 2.3 Cómo se fusionan el escaneo y lo manual
Cada arranque (y cada "Buscar de nuevo ahora") re-escanea las tres fuentes y fusiona con lo existente:
- Las entradas **manuales** no se tocan.
- En las **detectadas** se conservan los campos del usuario (`_PRESERVED_FIELDS`): `hidden`, `hover_background`, `favorite` y `category_locked`.
- Cada app se queda en la categoría donde la dejaste.
- Una app que ya no se detecta (desinstalada) desaparece de su lugar.

### 2.4 Robustez del guardado
- **Escritura atómica:** se escribe a un `.tmp` y se reemplaza con `os.replace()`, de modo que un corte a mitad de escritura no deja el archivo truncado.
- **Archivo corrupto:** se renombra a `.corrupt` y se arranca con valores por defecto, en vez de no abrir nunca más.
- **Archivo con forma rara pero JSON válido:** se normaliza al cargar (ids únicos, grupo por defecto presente, sin apps duplicadas entre grupos).
- **Settings:** si a un `settings.json` antiguo le falta una clave nueva, se completa con los valores por defecto sin perder lo que tenía.
- **Concurrencia:** un `threading.Lock` protege los datos, porque el escaneo corre en su propio hilo mientras el usuario puede estar editando.

---

## 3. Rendimiento con listas grandes

- **Menos de 60 apps:** scroll infinito clásico, con 3 copias de la lista apiladas y un salto silencioso en los bordes.
- **60 o más apps (sumando todas las categorías):** lista **virtualizada**, con un pool reciclado de ~15–20 tarjetas y un pool de títulos de categoría, dimensionados al área visible. Esta variante no hace loop; para listas tan grandes, el buscador es la forma principal de navegar.
- El "crecimiento" en hover **nunca cambia el tamaño real del widget** (solo se redibuja dentro del espacio ya reservado), para no recalcular el layout en cada frame.
- Un único `QTimer` anima todos los botones especiales y se pausa cuando la ventana está oculta.
- Un mecanismo en capas corrige el "hover pegado" (Qt solo actualiza el hover cuando el mouse se mueve de verdad, no cuando el contenido se mueve bajo un cursor quieto).

---

## 4. Estructura del código

```
spectrum_launcher/
├── main.py                  # punto de entrada
├── main.spec                # config de PyInstaller
├── requirements.txt
├── core/                    # lógica sin UI (testeable sin Windows)
│   ├── paths.py             # rutas; datos en %APPDATA% + migración
│   ├── debug_log.py         # log a archivo
│   ├── config_manager.py    # settings.json con merge de defaults
│   ├── auto_categories.py   # reglas de categorización automática
│   ├── launcher_manager.py  # el corazón: fusión, categorías, orden, favoritas, lock
│   ├── steam_detector.py
│   ├── shortcut_scanner.py
│   ├── uwp_detector.py
│   ├── icon_extractor.py
│   ├── scan_worker.py       # refresh() en un QThread
│   └── single_instance.py
├── ui/                      # PySide6
│   ├── main_window.py       # ventana, bandeja, scroll, búsqueda
│   ├── launcher_card.py     # tarjeta individual
│   ├── virtual_card_list.py # lista virtualizada
│   ├── expand_overlay.py    # panel de tarjeta expandida
│   ├── special_button.py
│   ├── add_app_dialog.py
│   ├── category_dialogs.py
│   ├── settings_window.py
│   ├── app_icon.py
│   ├── global_hotkey.py     # atajo global (ctypes)
│   └── text_utils.py
├── tests/                   # 89 tests (core + UI en modo offscreen)
└── tools/                   # scripts de diagnóstico de Steam
```

≈6.400 líneas de Python. La separación **`core/` sin UI** y **`ui/` con PySide6** es deliberada: toda la lógica importante se puede probar en cualquier sistema operativo.

---

## 5. Decisiones de diseño clave

- **PySide6 (LGPL)** en lugar de PyQt6 (GPL), por libertad de distribución.
- **Rutas absolutas** resueltas desde el propio proyecto o `.exe`, nunca desde el directorio de trabajo del proceso.
- **Datos del usuario separados del código**, para que actualizar el programa no pueda pisarlos.
- **Una categoría es un grupo:** reutiliza el esquema original, así un `launchers.json` de la v1 sigue siendo válido sin migrar.
- **Virtualizar solo por encima de un umbral:** el camino clásico para listas chicas queda intacto y el pool reciclado actúa solo donde hay un problema de rendimiento real.
- **Diálogos modales diferidos** con `QTimer.singleShot(0, ...)`, para no destruir una tarjeta mientras su propio evento sigue en la pila.
- **Recarga en caliente:** guardar en Configuración reconstruye la ventana sin reiniciar el proceso.

---

## 6. Dependencias

| Paquete | Mínimo | Para qué |
|---|---|---|
| PySide6 | ≥ 6.8 | Interfaz (Qt) |
| pywin32 | ≥ 311 | COM, GDI, APIs de Windows |
| vdf | ≥ 3.4 | Leer archivos de Steam |
| Pillow | ≥ 12.3.0 | Procesar iconos e imágenes |

Requiere **Windows 10/11**. La detección de Microsoft Store necesita Windows PowerShell (incluido por defecto) y se puede desactivar.

---

## 7. Instalación y ejecución

```
pip install -r requirements.txt
python main.py
```

Para generar un `.exe`: `pyinstaller main.spec`.

Tests:

```
python -m pytest tests/ -v
```

---

## 8. Limitaciones conocidas

- La categorización automática es solo por origen y ruta (juegos y Microsoft Store). No hay categorías semánticas como navegadores o desarrollo.
- No hay arrastrar y soltar entre categorías ni categorías plegables.
- Con los botones especiales en modo "Dentro de la lista" no se virtualiza, aunque haya cientos de apps.
- El resultado de PowerShell no se cachea entre escaneos muy seguidos.
- Los tests de UI no cubren el menú contextual real ni la animación de hover.
- La parte de virtualización y categorías se desarrolló contra Qt en modo offscreen; conviene un smoke test visual con 100+ apps antes de distribuir.

---

## 9. Ideas pendientes

1. Más reglas automáticas por lista de ejecutables conocidos (navegadores, desarrollo, multimedia).
2. Seguir partiendo `main_window.py` (`tray_manager.py`, `list_builder.py`, `scroll_controller.py`).
3. Reusar el pool virtualizado entre reconstrucciones.
4. Cachear el resultado de PowerShell.
5. Renombrar una app detectada sin tener que re-agregarla a mano.
6. "Abrir ubicación del archivo" y "Ejecutar como administrador" en el menú contextual.
7. Categorías plegables y arrastrar tarjetas entre categorías.
8. Copiar la imagen de fondo elegida a la carpeta de datos, para que no dependa de dónde esté el original.
