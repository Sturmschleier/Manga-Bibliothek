"""
gui/table.py
Tabellen-Darstellung: MangaTableModel (QAbstractTableModel) und
CellDelegate (zeichnet Zellinhalte inkl. der "+1"-Buttons selbst, ohne
ein echtes Widget pro Zelle - hält die Tabelle auch bei sehr vielen
Zeilen virtualisiert/schnell).
"""

import time

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate

import colors
import config

from .constants import (
    INCREMENTABLE_COLUMNS, PLUS_BTN_MARGIN, PLUS_BTN_WIDTH, ROW_ID_ROLE,
    RUCKSTAND_COLUMN, _ruckstand_value,
)

class MangaTableModel(QAbstractTableModel):
    """Zeigt eine (bereits gefilterte/sortierte) Liste von Puffer-Einträgen
    an. Hält keine eigene Kopie der Daten - `rows` referenziert dieselben
    Dicts wie der Speicher-Puffer der Hauptklasse, Änderungen (z.B. durch
    die "+1"-Buttons) wirken sich also direkt auf den Puffer aus."""

    def __init__(self, columns, labels, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.labels = labels
        self.rows = []
        self.colors_enabled = config.get_dict("colors_enabled")

    def set_rows(self, rows):
        # Die Farb-Konfiguration wird hier bewusst NICHT mehr gelesen -
        # refresh() (und damit set_rows) läuft bei jedem Tastendruck in
        # der Suche; eine Datei-/JSON-Lesung dabei wäre unnötiger I/O pro
        # Tastendruck. self.colors_enabled wird stattdessen einmalig bei
        # der Modell-Erstellung sowie gezielt nach dem Speichern im
        # Konfigurations-Dialog aktualisiert (siehe MangaLibraryApp).
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.labels[self.columns[section]]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self.rows[index.row()]
        col = self.columns[index.column()]

        if col == RUCKSTAND_COLUMN:
            if role == Qt.DisplayRole:
                diff = _ruckstand_value(entry)
                return "" if diff is None else str(diff)
            if role == Qt.BackgroundRole:
                return QColor(colors.zebra_color(index.row()))
            if role == Qt.ForegroundRole:
                return QColor(colors.DEFAULT_TEXT_COLOR)
            if role == ROW_ID_ROLE:
                return entry.get("id")
            return None

        if role == Qt.DisplayRole:
            return entry.get(col, "") or ""
        if role == Qt.BackgroundRole:
            if col == "titel" and entry.get("bestellt"):
                return QColor(colors.BESTELLT_COLOR)
            return QColor(colors.cell_background(col, entry.get(col, "") or "", index.row(), self.colors_enabled))
        if role == Qt.ForegroundRole:
            return QColor(colors.DEFAULT_TEXT_COLOR)
        if role == ROW_ID_ROLE:
            return entry.get("id")
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


class CellDelegate(QStyledItemDelegate):
    """Zeichnet Zellenhintergrund/-text selbst (statt echter Widgets pro
    Zelle) und zeichnet für "Bände (bis)"/"Gelesen bis" zusätzlich einen
    kleinen "+1"-Button, dessen Klick über `editorEvent` erkannt wird -
    ohne dafür ein echtes Widget pro Zeile anzulegen. Das hält die Tabelle
    auch bei sehr vielen Zeilen vollständig virtualisiert/schnell."""

    def __init__(self, columns, on_increment_baende, on_increment_gelesen, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.on_increment_baende = on_increment_baende
        self.on_increment_gelesen = on_increment_gelesen
        self._last_click = {}  # (row_id, col) -> Zeitpunkt (time.monotonic()) des letzten Klicks

    def _plus_rect(self, option):
        r = option.rect
        return QRect(r.right() - PLUS_BTN_WIDTH - PLUS_BTN_MARGIN, r.top() + 3, PLUS_BTN_WIDTH, r.height() - 6)

    def paint(self, painter, option, index):
        col = self.columns[index.column()]
        painter.save()

        bg = index.data(Qt.BackgroundRole)
        if bg:
            painter.fillRect(option.rect, bg)

        text = str(index.data(Qt.DisplayRole) or "")
        text_rect = option.rect.adjusted(4, 0, -4, 0)
        is_incrementable = col in INCREMENTABLE_COLUMNS
        if is_incrementable:
            text_rect.setRight(text_rect.right() - PLUS_BTN_WIDTH - PLUS_BTN_MARGIN)

        fg = index.data(Qt.ForegroundRole) or QColor("#1a1a1a")
        painter.setPen(fg)
        painter.drawText(text_rect, int(Qt.AlignVCenter | Qt.AlignLeft), text)

        if is_incrementable:
            btn_rect = self._plus_rect(option)
            painter.setPen(QColor("#888888"))
            painter.setBrush(QColor("#e2e2e2"))
            painter.drawRect(btn_rect)
            painter.setPen(QColor("#222222"))
            painter.drawText(btn_rect, int(Qt.AlignCenter), "+1")

        if option.state & QStyle.State_Selected:
            pen = QPen(QColor("#3366CC"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))

        painter.restore()

    def editorEvent(self, event, model, option, index):
        col = self.columns[index.column()]
        if col in INCREMENTABLE_COLUMNS and event.type() == QEvent.MouseButtonRelease:
            if self._plus_rect(option).contains(event.position().toPoint()):
                row_id = index.data(ROW_ID_ROLE)
                key = (row_id, col)
                now = time.monotonic()
                # Bei einem Doppelklick feuert mouseReleaseEvent (und damit
                # dieses editorEvent) zweimal - einmal je Klick. Ohne diese
                # Absicherung würde das ein doppeltes Erhöhen auslösen.
                if now - self._last_click.get(key, 0.0) < QApplication.doubleClickInterval() / 1000:
                    return True
                self._last_click[key] = now
                if col == "baende_bis":
                    self.on_increment_baende(row_id)
                else:
                    self.on_increment_gelesen(row_id)
                return True
        return False
