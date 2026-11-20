"""
category_dialogs.py
----------------------
Dialogo compartido para pedir el nombre de una categoria (crear o
renombrar). Vive aparte porque lo usan dos lugares distintos -- el menu
contextual de una tarjeta (ui/main_window.py, "Nueva categoria...") y el
panel de Configuracion (ui/settings_window.py) -- y la validacion tiene
que ser identica en los dos.
"""

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox


def ask_category_name(parent, manager, title: str, label: str, initial: str = "",
                      exclude_group_id=None):
    """Pide un nombre hasta que sea valido o el usuario cancele.

    Devuelve el nombre ya recortado, o None si cancelo. La validacion
    (vacio / demasiado largo / repetido) la hace el propio
    LauncherManager (check_category_title), no esta funcion: asi la
    regla vive en un solo lugar y create_category/rename_category
    aplican la misma como red de seguridad.

    Si el nombre no es valido se explica por que y se vuelve a preguntar
    con lo que el usuario habia escrito, en vez de cerrar el dialogo y
    hacerle empezar de nuevo."""
    text = initial
    while True:
        text, accepted = QInputDialog.getText(
            parent, title, label, QLineEdit.EchoMode.Normal, text
        )
        if not accepted:
            return None
        error = manager.check_category_title(text, exclude_group_id)
        if not error:
            return text.strip()
        QMessageBox.warning(parent, title, error)
