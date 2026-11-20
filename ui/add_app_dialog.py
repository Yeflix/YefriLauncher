"""
add_app_dialog.py
--------------------
FASE 5: dialogo para agregar manualmente un programa que la deteccion
automatica no haya encontrado (por eso el boton "Agregar app" en la
ventana principal).
"""

import hashlib
import os

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class AddAppDialog(QDialog):
    def __init__(self, parent=None, categories=None):
        """categories: lista de LauncherManager.categories(). Si hay mas
        de una se ofrece elegir en cual se agrega la app (por defecto,
        la categoria por defecto); con una sola no se muestra el
        selector -- no hay nada que elegir."""
        super().__init__(parent)
        self.setWindowTitle("Agregar app")
        self.setModal(True)
        self.setMinimumWidth(380)

        self.result_entry = None
        self.result_group_id = None  # None = el manager decide (categoria por defecto)

        self._category_combo = None
        if categories and len(categories) > 1:
            self._category_combo = QComboBox()
            default_index = 0
            for i, cat in enumerate(categories):
                self._category_combo.addItem(cat["title"], cat["group_id"])
                if cat.get("is_default"):
                    default_index = i
            self._category_combo.setCurrentIndex(default_index)

        self._name_edit = QLineEdit()
        self._path_edit = QLineEdit()

        browse_btn = QPushButton("Examinar...")
        browse_btn.clicked.connect(self._browse)

        path_row = QHBoxLayout()
        path_row.addWidget(self._path_edit)
        path_row.addWidget(browse_btn)

        form = QFormLayout()
        form.addRow("Nombre:", self._name_edit)
        form.addRow("Ejecutable (.exe):", path_row)
        if self._category_combo is not None:
            form.addRow("Categoría:", self._category_combo)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Agregar")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona el ejecutable", "", "Ejecutables (*.exe)"
        )
        if not path:
            return
        self._path_edit.setText(path)
        if not self._name_edit.text():
            self._name_edit.setText(os.path.splitext(os.path.basename(path))[0])

    def _on_accept(self):
        name = self._name_edit.text().strip()
        target = self._path_edit.text().strip()

        if not name or not target:
            # Antes esto simplemente no hacia nada -- el dialogo se
            # quedaba ahi sin cerrar y sin ninguna pista de por que,
            # como si el click no hubiera funcionado.
            QMessageBox.warning(
                self, "Faltan datos",
                "Completa el nombre y la ruta del ejecutable antes de agregar.",
            )
            return

        if not os.path.exists(target):
            # No bloquea el agregado (la ruta podria estar en una unidad
            # de red momentaneamente desconectada, por ejemplo), pero
            # avisa de entrada en vez de dejar que el usuario se entere
            # recien cuando la tarjeta no abra nada al hacerle click.
            proceed = QMessageBox.question(
                self, "La ruta no existe",
                f"No se encontró este archivo:\n{target}\n\n¿Agregarlo de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        # normpath solo para el hash del id (colapsa variaciones de
        # formato del MISMO path, igual que shortcut_scanner._make_id) --
        # el 'target' que se guarda de verdad queda tal cual lo escribio
        # o eligio el usuario.
        normalized = os.path.normpath(target).lower()
        entry_id = "manual_" + hashlib.md5(normalized.encode("utf-8")).hexdigest()[:10]
        self.result_entry = {
            "id": entry_id,
            "name": name,
            "type": "shortcut",
            "target": target,
            "icon": "auto",
            "close_after_launch": True,
        }
        if self._category_combo is not None:
            self.result_group_id = self._category_combo.currentData()
        self.accept()
