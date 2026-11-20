"""
conftest.py
-------------
Permite correr los tests de core/ tambien fuera de Windows.

El proyecto es Windows-only en ejecucion (winreg, win32com, win32gui...),
pero la LOGICA que mas vale la pena testear -- fusion de datos al
escanear, persistencia, orden, concurrencia -- no depende de nada de
eso. Stubeando los modulos nativos, esa logica se puede verificar en
cualquier maquina (y en CI), en vez de necesitar una VM con Windows para
correr un solo assert.

En Windows estos stubs no se instalan: si el modulo real importa, se usa
ese.
"""

import sys
import types


def _ensure(name: str, build):
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = build()


def _win32gui():
    m = types.ModuleType("win32gui")
    m.ExtractIconEx = lambda *a, **k: ([], [])
    m.DestroyIcon = lambda *a, **k: None
    m.GetDC = lambda *a, **k: 1
    m.ReleaseDC = lambda *a, **k: None
    m.DeleteObject = lambda *a, **k: None
    return m


def _win32ui():
    m = types.ModuleType("win32ui")

    class _Bmp:
        def CreateCompatibleBitmap(self, *a, **k): pass
        def GetInfo(self): return {"bmWidth": 1, "bmHeight": 1}
        def GetBitmapBits(self, *a, **k): return bytes(4)
        def GetHandle(self): return 1

    class _DC:
        def CreateCompatibleDC(self): return _DC()
        def SelectObject(self, *a, **k): pass
        def DrawIcon(self, *a, **k): pass
        def DeleteDC(self): pass

    m.CreateDCFromHandle = lambda *a, **k: _DC()
    m.CreateBitmap = lambda *a, **k: _Bmp()
    return m


def _winreg():
    m = types.ModuleType("winreg")
    m.HKEY_CURRENT_USER = 0

    def _missing(*a, **k):
        raise FileNotFoundError()

    m.OpenKey = _missing
    m.QueryValueEx = _missing
    m.CloseKey = lambda *a, **k: None
    return m


def _vdf():
    m = types.ModuleType("vdf")
    m.load = lambda f: {}
    return m


def _pythoncom():
    m = types.ModuleType("pythoncom")
    m.CoInitialize = lambda *a, **k: None
    m.CoUninitialize = lambda *a, **k: None
    return m


def _win32com_client():
    pkg = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")

    def Dispatch(*a, **k):
        class _Shell:
            def CreateShortcut(self, *a, **k):
                raise OSError("stub")
        return _Shell()

    client.Dispatch = Dispatch
    pkg.client = client
    sys.modules.setdefault("win32com", pkg)
    return client


_ensure("win32gui", _win32gui)
_ensure("win32ui", _win32ui)
_ensure("winreg", _winreg)
_ensure("vdf", _vdf)
_ensure("pythoncom", _pythoncom)
try:
    __import__("win32com.client")
except ImportError:
    sys.modules["win32com.client"] = _win32com_client()
