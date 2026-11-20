# -*- mode: python ; coding: utf-8 -*-
"""
main.spec -- empaquetado de SPECTRUM Launcher con PyInstaller.

Uso (desde la carpeta del proyecto, con el entorno donde instalaste
requirements.txt):

    pip install pyinstaller
    pyinstaller --noconfirm main.spec

Resultado: dist\\SpectrumLauncher\\SpectrumLauncher.exe  (carpeta completa:
hay que distribuirla ENTERA, no solo el .exe).

Variables de entorno opcionales (cmd: `set NOMBRE=1`):
    SPECTRUM_CONSOLE=1   build de DEPURACION con consola visible, para ver
                         errores de arranque que en modo ventana no se ven.
    SPECTRUM_ONEFILE=1   un unico .exe en vez de carpeta. Arranca mas lento
                         (se extrae a una carpeta temporal en cada inicio)
                         y los antivirus lo marcan mas seguido: para un
                         programa que vive en la bandeja se recomienda la
                         carpeta (el valor por defecto).

Datos del usuario: NO van dentro del paquete. launchers.json, settings.json
y la cache de iconos viven en %APPDATA%\\SpectrumLauncher (ver
core/paths.py), asi que reemplazar la carpeta dist\\ por una version nueva
no borra imagenes de fondo, favoritas ni categorias.

Por que no hay `datas`: el codigo no carga ningun recurso desde disco
(los estilos estan en el codigo y el icono de la bandeja se dibuja en
ui/app_icon.py; assets/icons/spectrum.ico solo se usa como icono del
.exe). Si algun dia se cargan archivos de assets/ en ejecucion,
agregarlos aca: datas=[("assets", "assets")].
"""

import os

APP_NAME = "SpectrumLauncher"

ONEFILE = os.environ.get("SPECTRUM_ONEFILE") == "1"
CONSOLE = os.environ.get("SPECTRUM_CONSOLE") == "1"

# Icono del .exe (el de la bandeja se genera por codigo y no depende de
# esto). Se genera una vez con:  python tools/make_icon.py
# Si el archivo no existe, el .exe sale con el icono generico de Python.
_ICON_PATH = os.path.join(SPECPATH, "assets", "icons", "spectrum.ico")
ICON = _ICON_PATH if os.path.isfile(_ICON_PATH) else None

# Imports que el analisis estatico de PyInstaller no siempre detecta bien
# en pywin32 (COM y modulos que se cargan por nombre en tiempo de ejecucion).
HIDDEN_IMPORTS = [
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "win32gui",
    "win32ui",
    "win32timezone",
    "vdf",
]

# Modulos que el proyecto no usa y que, si estan instalados en el entorno,
# inflan el paquete en cientos de MB (PySide6 trae decenas de submodulos).
# Se usan QtCore, QtGui, QtWidgets y QtNetwork: todo lo demas se excluye.
EXCLUDES = [
    "tkinter",
    "pytest",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtTextToSpeech",
    "PySide6.QtSpatialAudio",
    "PySide6.QtHttpServer",
]

a = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        icon=ICON,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=CONSOLE,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        icon=ICON,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        # UPX desactivado: comprime las DLL de Qt/pywin32, no ahorra casi
        # nada, y es una causa clasica de falsos positivos de antivirus y de
        # DLL que dejan de cargar.
        upx=False,
        console=CONSOLE,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
