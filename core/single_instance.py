"""
single_instance.py
--------------------
Evita que se abran dos copias del launcher a la vez, y le avisa a la que
ya estaba corriendo para que se muestre.

Por que hace falta
---------------------
La app vive en la bandeja del sistema, asi que es muy facil terminar con
dos instancias sin darse cuenta (esta en el inicio de Windows Y ademas
se hace doble click en el .exe). Con dos corriendo:
- Aparecen dos iconos de bandeja.
- El segundo RegisterHotKey falla porque la combinacion ya esta tomada
  (ver ui/global_hotkey.py): el atajo global de esa instancia queda
  muerto en silencio.
- Las dos escriben config/launchers.json. El threading.Lock de
  LauncherManager protege entre HILOS del mismo proceso, no entre
  procesos distintos: os.replace evita que el archivo quede corrupto,
  pero gana el ultimo que escribe, asi que se pierden cambios (una
  imagen de fondo recien asignada, una app recien ocultada) sin ningun
  aviso.

Como funciona
----------------
QLocalServer/QLocalSocket (named pipe en Windows) en vez de un archivo
de lock: si el proceso muere de golpe (kill, corte de luz), el sistema
operativo cierra el pipe solo, asi que no queda un lock "fantasma" que
impida abrir la app despues -- que es el modo tipico de fallar de los
lock-files caseros.

Ademas del guard, sirve de canal: la segunda instancia manda _SHOW_MSG
y se cierra; la primera lo recibe y se muestra. Asi, volver a hacer
doble click en el .exe se comporta como "traer la ventana al frente",
que es lo que el usuario espera que pase.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# Nombre del pipe. Incluye algo especifico del proyecto para no chocar
# con otra app que use la misma tecnica.
_SERVER_NAME = "spectrum_launcher_single_instance"
_SHOW_MSG = b"show"
_CONNECT_TIMEOUT_MS = 500


class SingleInstanceGuard(QObject):
    """Emite show_requested cuando otra instancia intenta arrancar."""

    show_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None

    def try_acquire(self) -> bool:
        """True si esta es la UNICA instancia (y queda escuchando por si
        arranca otra). False si ya habia una corriendo -- en ese caso ya
        se le aviso para que se muestre, y el llamador deberia salir sin
        abrir nada (ver main.py)."""
        if self._notify_existing():
            return False

        self._server = QLocalServer(self)
        # Si una instancia anterior murio de forma sucia, el nombre puede
        # quedar tomado aunque no haya nadie escuchando. removeServer()
        # limpia ese residuo. Es seguro llamarlo aca porque ya sabemos,
        # por _notify_existing(), que nadie contesto en ese pipe.
        QLocalServer.removeServer(_SERVER_NAME)
        if not self._server.listen(_SERVER_NAME):
            # No se pudo escuchar por un motivo inesperado (permisos,
            # etc.). Se deja arrancar igual: es preferible una app que
            # abre sin el guard a una que no abre.
            self._server = None
            return True

        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _notify_existing(self) -> bool:
        """Intenta hablarle a una instancia previa. True si habia una."""
        socket = QLocalSocket()
        socket.connectToServer(_SERVER_NAME)
        if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
            return False
        socket.write(_SHOW_MSG)
        socket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def _on_new_connection(self):
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        # readyRead en vez de leer aca mismo: la conexion recien se
        # acepto y los bytes pueden no haber llegado todavia.
        socket.readyRead.connect(lambda: self._on_ready_read(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket):
        if socket.readAll().data().strip() == _SHOW_MSG:
            self.show_requested.emit()

    def release(self):
        if self._server is not None:
            self._server.close()
            self._server = None
