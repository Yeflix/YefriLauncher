"""
global_hotkey.py
-------------------
Registra un atajo de teclado GLOBAL de Windows (funciona aunque la
ventana no tenga el foco) para mostrar/ocultar el launcher desde
cualquier lugar. Usa la API nativa RegisterHotKey (via ctypes) + un
QAbstractNativeEventFilter que intercepta el mensaje WM_HOTKEY dentro
del loop de eventos de Qt -- el patron estandar para esto en Windows,
sin necesitar un hilo ni una libreria externa de mas.

Especifico de Windows (usa ctypes.windll, que no existe en Linux/Mac).
En cualquier otro sistema operativo simplemente no hace nada. No se
pudo probar en este entorno de desarrollo (el sandbox corre Linux) --
probar en Windows real antes de confiar en el atajo para uso diario.
"""

import sys

from PySide6.QtCore import QAbstractNativeEventFilter

from core.debug_log import log as _log

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _WM_HOTKEY = 0x0312
    _MOD_NOREPEAT = 0x4000

    _MODIFIERS = {
        "ctrl": 0x0002, "control": 0x0002,
        "alt": 0x0001,
        "shift": 0x0004,
        "win": 0x0008, "meta": 0x0008,
    }

    _VK_KEYS = {chr(c).lower(): c for c in range(0x41, 0x5B)}  # a-z
    _VK_KEYS.update({str(d): 0x30 + d for d in range(10)})     # 0-9
    _VK_KEYS.update({
        "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
        "esc": 0x1B, "escape": 0x1B,
    })
    _VK_KEYS.update({f"f{n}": 0x70 + (n - 1) for n in range(1, 13)})  # f1-f12


def _parse_hotkey(hotkey_str: str):
    """'ctrl+alt+space' -> (modificadores_bitmask, codigo_de_tecla)."""
    modifiers = 0
    vk = None
    for part in hotkey_str.split("+"):
        key = part.strip().lower()
        if key in _MODIFIERS:
            modifiers |= _MODIFIERS[key]
        elif key in _VK_KEYS:
            vk = _VK_KEYS[key]
    return modifiers, vk


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback):
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam == self._hotkey_id:
                self._callback()
        return False, 0


class GlobalHotkey:
    """Uso:
        hotkey = GlobalHotkey(app, "ctrl+alt+space", on_triggered=fn)
        ...
        hotkey.unregister()  # al cerrar el programa de verdad
    """

    _next_id = 1

    def __init__(self, app, hotkey_str: str, on_triggered):
        self._registered = False
        # True si se intento registrar y no se pudo (atajo ilegible o ya
        # tomado por otro programa): la ventana se lo avisa al usuario.
        self.failed = False
        self._filter = None
        self._app = app
        self._id = GlobalHotkey._next_id
        GlobalHotkey._next_id += 1

        if not _IS_WINDOWS:
            return  # no-op fuera de Windows

        modifiers, vk = _parse_hotkey(hotkey_str)
        if vk is None:
            _log(f"GlobalHotkey: no se pudo interpretar '{hotkey_str}', se ignora.")
            self.failed = True
            return

        ok = ctypes.windll.user32.RegisterHotKey(None, self._id, modifiers | _MOD_NOREPEAT, vk)
        if not ok:
            _log(
                f"GlobalHotkey: no se pudo registrar '{hotkey_str}' "
                "(¿ya esta en uso por otro programa?)."
            )
            self.failed = True
            return

        self._registered = True
        self._filter = _HotkeyEventFilter(self._id, on_triggered)
        app.installNativeEventFilter(self._filter)

    def unregister(self):
        """Libera el atajo y quita el filtro nativo de la aplicacion.
        Idempotente: se puede llamar varias veces (cierre ordenado +
        cambio de atajo en caliente) sin efecto la segunda vez."""
        if self._registered and _IS_WINDOWS:
            ctypes.windll.user32.UnregisterHotKey(None, self._id)
            self._registered = False
        if self._filter is not None:
            try:
                self._app.removeNativeEventFilter(self._filter)
            except RuntimeError:
                pass  # la QApplication ya se estaba destruyendo
            self._filter = None
