"""Utilidad chica y compartida para truncar ("...") el texto de un
QLabel de una sola linea que no entra en el ancho disponible, en vez de
dejar que Qt lo recorte a lo bruto en el borde del widget (sin "...",
y a veces solapandose con lo que venga despues).

La usan los titulos de categoria -- tanto en la lista normal
(MainWindow._build_group_stack) como en la virtualizada
(VirtualCardList._place_rows) -- y el nombre de la app en
ExpandOverlay. Mismo criterio que ya usaba LauncherCard para el nombre
de cada app (ver ui/launcher_card.py, _update_name_elision): texto
elidido + el texto completo como tooltip, solo cuando de verdad hizo
falta truncar."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel


def elide_label_text(label: QLabel, full_text: str, max_width: int) -> None:
    fm = QFontMetrics(label.font())
    elided = fm.elidedText(full_text, Qt.TextElideMode.ElideRight, max(0, max_width))
    label.setText(elided)
    label.setToolTip(full_text if elided != full_text else "")
