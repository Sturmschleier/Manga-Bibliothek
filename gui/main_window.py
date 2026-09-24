"""
gui/main_window.py
Hauptfenster (MangaLibraryApp): Speicher-Puffer, Undo/Redo, Toolbar,
Filter, Tabelle, Seitenleiste, Live-Log, ISBN-Abgleich-Steuerung.

Wichtig: Alle Änderungen (neuer Eintrag, Bearbeiten, Löschen, +1-Buttons,
CSV-Import) wirken zunächst nur auf einen Puffer im Speicher (self.data).
Erst ein Klick auf "💾 Speichern" schreibt den kompletten Bestand in die
lokale Datenbank. Solange ungespeicherte Änderungen bestehen, zeigen
Fenstertitel und Statuszeile das deutlich an; beim Schließen des Fensters
und vor einem Google-Drive-Upload wird ebenfalls nachgefragt.

Die Tabelle nutzt QTableView + ein eigenes QAbstractTableModel: Qt erzeugt
dabei nur für die aktuell sichtbaren Zeilen tatsächlich Zeichen-/Klick-
Aufwand ("virtualisiert") - unabhängig von der Gesamtgröße der Sammlung.
"""

import copy
import threading
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSizePolicy,
    QSplitter, QTableView, QVBoxLayout, QWidget,
)

import changelog
import colors
import config
import csv_export
import database as db
import import_csv
import logic
import sorting

from .constants import (
    APP_TITLE, COL_DEFAULT_WIDTHS, DISPLAY_COLUMNS, DISPLAY_LABELS,
    INCREMENTABLE_COLUMNS, MAX_UNDO_STEPS, ROW_ID_ROLE, RUCKSTAND_COLUMN,
    VOE1_FILTER_OPTIONS, _entry_voe_dates, _ruckstand_value, _voe1_category,
)
from .dialogs import ConfigDialog, EntryDialog, IsbnLookupDialog
from .isbn_view import IsbnResultWindow, IsbnWorkerSignals
from .table import CellDelegate, MangaTableModel

class MangaLibraryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1450, 780)

        config.ensure_file_exists()
        changelog.archive_old_entries()

        db.init_db()

        self.data = db.load_all()   # Speicher-Puffer: Liste von Dicts
        self.dirty = False
        self.next_temp_id = -1      # negative IDs für noch nicht gespeicherte, neue Einträge

        self._clean_snapshot = copy.deepcopy(self.data)  # Stand des letzten Ladens/Speicherns (für "dirty" & Undo)
        self.undo_stack = []
        self.redo_stack = []
        self._pending_redo_backup = None  # siehe _push_undo_snapshot/_discard_pending_snapshot

        self.sort_column = "titel"
        self.sort_reverse = False
        self.selected_row_id = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        self._build_toolbar(root)
        self._build_filter_bar(root)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self._build_table(self.main_splitter)
        self._build_sidebar(self.main_splitter)
        root.addWidget(self.main_splitter, 1)
        self._sidebar_sized = False

        self.statusBar()  # QMainWindow-eigene Statuszeile aktivieren
        self._build_footer_legend()

        self._autosize_titel_column()  # einmalig für den initial geladenen Bestand
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        # Die Aufteilung der Seitenleiste bewusst erst hier (beim
        # tatsächlichen Anzeigen) vornehmen, nicht schon im __init__: erst
        # jetzt kennt Qt die endgültige Fensterbreite (die Tabelle kann das
        # Fenster durch ihre vielen Spalten breiter ziehen, als per
        # resize() angefordert wurde).
        if not self._sidebar_sized:
            self._apply_sidebar_width()
            self._sidebar_sized = True

    def _apply_sidebar_width(self):
        # Wirkt nur einmalig beim allerersten Anzeigen (siehe showEvent) -
        # eine spätere Änderung in der Konfiguration wird erst beim
        # nächsten Programmstart übernommen (siehe README), damit ein
        # zwischenzeitlich von Hand verschobener Trenner nicht ungefragt
        # überschrieben wird.
        try:
            fraction = config.get_float("sidebar_width_fraction", 0.15)
            fraction = max(0.05, min(0.6, fraction))  # gegen unsinnige/extreme Werte absichern
            total = self.main_splitter.width()
            sidebar_width = max(1, int(total * fraction))
            table_width = max(1, total - sidebar_width)
            self.main_splitter.setSizes([table_width, sidebar_width])
        except (TypeError, ValueError, OverflowError):
            # Ein kaputter Konfigurationswert darf den Programmstart nicht
            # verhindern - im Zweifel bleibt die vom Splitter selbst
            # gewählte Standardaufteilung einfach stehen.
            pass

    # ------------------------------------------------------------ Puffer

    def _log(self, message: str):
        """Protokolliert eine Änderung: dauerhaft in der Log-Datei (siehe
        changelog.py, mit 6-Monats-Archivierung) UND live in der
        Seitenleiste der aktuellen Sitzung."""
        line = changelog.log_change(message)
        self.live_log_view.appendPlainText(line)
        self.live_log_view.verticalScrollBar().setValue(self.live_log_view.verticalScrollBar().maximum())


    def _mark_dirty(self):
        """Prüft, ob sich der Puffer vom zuletzt geladenen/gespeicherten
        Stand unterscheidet - statt einfach nur ein Flag zu setzen. So
        verschwindet der "ungespeicherte Änderungen"-Hinweis auch korrekt
        wieder, wenn man z.B. per Rückgängig exakt zum gespeicherten Stand
        zurückkehrt."""
        self.dirty = (self.data != self._clean_snapshot)
        self._update_title()

    def _update_title(self):
        self.setWindowTitle(APP_TITLE + (" *" if self.dirty else ""))

    def _find_entry(self, row_id):
        for entry in self.data:
            if entry["id"] == row_id:
                return entry
        return None

    def _distinct_values(self, column):
        values = {(e.get(column) or "").strip() for e in self.data}
        values.discard("")
        return sorted(values, key=str.lower)

    # ------------------------------------------------------- Undo/Redo

    def _push_undo_snapshot(self):
        """
        Vor jeder GEPLANTEN puffer-verändernden Aktion aufzurufen: merkt
        sich den Stand VOR der Änderung für "Rückgängig".

        Löscht die "Wiederholen"-Historie bewusst NOCH NICHT - das
        passiert erst in `_commit_pending_action()`, sobald die Aktion
        tatsächlich stattgefunden hat. Bricht die Aktion stattdessen ab
        (z.B. ungültige Eingabe, geblockte "+1"-Erhöhung, leerer
        CSV-Import), `_discard_pending_snapshot()` aufrufen - dann bleibt
        eine zuvor vorhandene "Wiederholen"-Historie unangetastet, statt
        grundlos verworfen zu werden.
        """
        self._pending_redo_backup = list(self.redo_stack)
        self.undo_stack.append((copy.deepcopy(self.data), self.next_temp_id))
        if len(self.undo_stack) > MAX_UNDO_STEPS:
            self.undo_stack.pop(0)
        self._update_undo_redo_actions()

    def _commit_pending_action(self):
        """Nach einer ERFOLGREICHEN, per `_push_undo_snapshot()` vorbereiteten
        Änderung aufzurufen: verwirft jetzt tatsächlich die "Wiederholen"-
        Historie (eine neue Aktion macht die alte Zukunft ungültig)."""
        self.redo_stack.clear()
        self._pending_redo_backup = None
        self._update_undo_redo_actions()

    def _discard_pending_snapshot(self):
        """Nach einer FEHLGESCHLAGENEN/abgebrochenen, per
        `_push_undo_snapshot()` vorbereiteten Aktion aufzurufen: verwirft
        den zuvor gemerkten Stand wieder, ohne die "Wiederholen"-Historie
        anzutasten."""
        if self.undo_stack:
            self.undo_stack.pop()
        if self._pending_redo_backup is not None:
            self.redo_stack = self._pending_redo_backup
            self._pending_redo_backup = None
        self._update_undo_redo_actions()

    def _update_undo_redo_actions(self):
        self.undo_btn.setEnabled(bool(self.undo_stack))
        self.redo_btn.setEnabled(bool(self.redo_stack))

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append((copy.deepcopy(self.data), self.next_temp_id))
        self.data, self.next_temp_id = self.undo_stack.pop()
        self.selected_row_id = None
        self._mark_dirty()
        self._update_undo_redo_actions()
        self._autosize_titel_column()
        self.refresh()
        self.statusBar().showMessage("Rückgängig gemacht.", 3000)
        self._log("Rückgängig gemacht.")

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append((copy.deepcopy(self.data), self.next_temp_id))
        self.data, self.next_temp_id = self.redo_stack.pop()
        self.selected_row_id = None
        self._mark_dirty()
        self._update_undo_redo_actions()
        self._autosize_titel_column()
        self.refresh()
        self.statusBar().showMessage("Wiederholt.", 3000)
        self._log("Wiederholt.")

    def save(self):
        """Schreibt den kompletten Puffer in die Datenbank."""
        count = len(self.data)
        self.data = db.replace_all(self.data)
        self._clean_snapshot = copy.deepcopy(self.data)
        self.dirty = False
        self.selected_row_id = None
        self._update_title()
        self.refresh()
        self.statusBar().showMessage(f"Gespeichert – {len(self.data)} Einträge", 5000)
        self._log(f"Gespeichert ({count} Einträge).")

    def closeEvent(self, event):
        if not self.dirty:
            event.accept()
            return
        answer = QMessageBox.question(
            self, "Ungespeicherte Änderungen",
            "Es gibt ungespeicherte Änderungen. Vor dem Beenden speichern?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if answer == QMessageBox.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.Yes:
            self.save()
        event.accept()

    # ------------------------------------------------------------------ UI

    def _build_toolbar(self, root):
        bar = QHBoxLayout()

        bar.addWidget(QLabel("Suche:"))
        self.search_input = QLineEdit()
        self.search_input.setFixedWidth(240)
        self.search_input.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search_input)

        bar.addSpacing(12)
        add_btn = QPushButton("+ Neuer Eintrag")
        add_btn.clicked.connect(self.open_add_dialog)
        bar.addWidget(add_btn)

        edit_btn = QPushButton("Bearbeiten")
        edit_btn.clicked.connect(self.edit_selected)
        bar.addWidget(edit_btn)

        delete_btn = QPushButton("Löschen")
        delete_btn.clicked.connect(self.delete_selected)
        bar.addWidget(delete_btn)

        bar.addWidget(self._vline())

        self.undo_btn = QPushButton("↶ Rückgängig")
        self.undo_btn.setShortcut(QKeySequence.Undo)
        self.undo_btn.setToolTip("Letzte Änderung rückgängig machen (Strg+Z)")
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.setEnabled(False)
        bar.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("↷ Wiederholen")
        self.redo_btn.setShortcut(QKeySequence.Redo)
        self.redo_btn.setToolTip("Rückgängig gemachte Änderung wiederholen (Strg+Umschalt+Z)")
        self.redo_btn.clicked.connect(self.redo)
        self.redo_btn.setEnabled(False)
        bar.addWidget(self.redo_btn)

        bar.addWidget(self._vline())

        self.save_btn = QPushButton("💾 Speichern")
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 4px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #43A047; }"
        )
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)

        bar.addWidget(self._vline())

        import_btn = QPushButton("CSV importieren")
        import_btn.clicked.connect(self.import_csv_dialog)
        bar.addWidget(import_btn)

        export_btn = QPushButton("CSV exportieren")
        export_btn.clicked.connect(self.export_csv_dialog)
        bar.addWidget(export_btn)

        bar.addWidget(self._vline())

        upload_btn = QPushButton("⬆ Zu Google Drive sichern")
        upload_btn.clicked.connect(self.drive_upload)
        bar.addWidget(upload_btn)

        download_btn = QPushButton("⬇ Von Google Drive laden")
        download_btn.clicked.connect(self.drive_download)
        bar.addWidget(download_btn)

        bar.addWidget(self._vline())

        isbn_btn = QPushButton("🔍 ISBN-Abgleich / Bestellliste")
        isbn_btn.clicked.connect(self.open_isbn_lookup_dialog)
        bar.addWidget(isbn_btn)

        bar.addWidget(self._vline())
        bar.addWidget(self._build_colors_menu_button())

        bar.addStretch(1)
        root.addLayout(bar)

    def _build_colors_menu_button(self):
        """
        Menü-Button zum Ein-/Ausschalten der Farbcodierung je Kategorie
        (VÖ +1, Komplett/Beendet, Verlag) - schreibt weiterhin in
        config.json (colors_enabled), jetzt aber zusätzlich direkt aus der
        Oberfläche erreichbar, nicht mehr nur per Hand-Bearbeiten der
        Konfigurationsdatei.
        """
        btn = QPushButton("🎨 Farben")
        btn.setToolTip("Farbcodierung je Kategorie ein-/ausschalten (dauerhaft gespeichert)")
        menu = QMenu(btn)

        self._color_actions = {}
        enabled = config.get_dict("colors_enabled")
        for key, label in (
            ("voe1", "VÖ +1 (Beendet/TBA/Gestoppt/NA)"),
            ("komplett_beendet", "Komplett/Beendet"),
            ("verlag", "Verlag"),
        ):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(enabled.get(key, True))
            action.toggled.connect(lambda checked, k=key: self._on_color_toggle(k, checked))
            self._color_actions[key] = action

        btn.setMenu(menu)
        return btn

    def _on_color_toggle(self, key, checked):
        cfg = config.load()
        colors_enabled = dict(cfg.get("colors_enabled") or {})
        colors_enabled[key] = checked
        config.set_value("colors_enabled", colors_enabled)
        self.model.colors_enabled = config.get_dict("colors_enabled")
        self.refresh()

    def _build_filter_bar(self, root):
        bar = QHBoxLayout()

        config_btn = QPushButton("⚙ Konfiguration")
        config_btn.setToolTip("Zentrale Konfigurationsdatei (config.json) bearbeiten")
        config_btn.clicked.connect(self.open_config_dialog)
        bar.addWidget(config_btn)

        bar.addWidget(self._vline())

        self.follow_selection_checkbox = QCheckBox("Nach Bearbeitung zur Zeile springen")
        self.follow_selection_checkbox.setChecked(config.get("follow_selection_after_edit", True))
        self.follow_selection_checkbox.setToolTip(
            "Wenn aktiv: springt die Ansicht nach dem Bearbeiten/Sortieren automatisch zum "
            "bearbeiteten Eintrag. Wenn deaktiviert: die aktuelle Scroll-Position bleibt erhalten.\n"
            "Der Wert wird dauerhaft in der Konfigurationsdatei gemerkt."
        )
        self.follow_selection_checkbox.toggled.connect(
            lambda checked: config.set_value("follow_selection_after_edit", checked)
        )
        bar.addWidget(self.follow_selection_checkbox)

        self.exclude_gestoppt_checkbox = QCheckBox("Gestoppt: keine Berechnung")
        self.exclude_gestoppt_checkbox.setChecked(config.get("exclude_gestoppt_from_stats", False))
        self.exclude_gestoppt_checkbox.setToolTip(
            "Wenn aktiv: Titel mit VÖ +1 = „Gestoppt“ fließen nicht in die Statistik-Box "
            "und die Gesamt/Gelesen/Offen-Bilanz je Typ ein.\n"
            "Der Wert wird dauerhaft in der Konfigurationsdatei gemerkt."
        )
        self.exclude_gestoppt_checkbox.toggled.connect(self._on_exclude_gestoppt_toggled)
        bar.addWidget(self.exclude_gestoppt_checkbox)

        bar.addWidget(self._vline())

        bar.addWidget(QLabel("Filter – Verlag:"))
        self.verlag_filter = QComboBox()
        self.verlag_filter.setMinimumWidth(160)
        self.verlag_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.verlag_filter)

        bar.addSpacing(16)
        bar.addWidget(QLabel("VÖ +1:"))
        self.voe1_filter = QComboBox()
        self.voe1_filter.addItems(VOE1_FILTER_OPTIONS)
        self.voe1_filter.setMinimumWidth(120)
        self.voe1_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.voe1_filter)

        reset_btn = QPushButton("Filter zurücksetzen")
        reset_btn.clicked.connect(self._reset_filters)
        bar.addSpacing(16)
        bar.addWidget(reset_btn)

        bar.addStretch(1)
        root.addLayout(bar)

    def _on_exclude_gestoppt_toggled(self, checked):
        config.set_value("exclude_gestoppt_from_stats", checked)
        self.refresh()

    def open_config_dialog(self):
        dlg = ConfigDialog(self)
        if dlg.exec():
            # Sofort wirksame Einstellungen aus der (evtl. geänderten)
            # Konfiguration übernehmen, ohne dass ein Neustart nötig ist.
            # Ausnahme: "sidebar_width_fraction" wirkt bewusst erst beim
            # nächsten Programmstart (siehe README) - eine sofortige
            # Anwendung würde sonst eine bereits von Hand verschobene
            # Seitenleiste ungefragt wieder überschreiben.
            self.follow_selection_checkbox.blockSignals(True)
            self.follow_selection_checkbox.setChecked(config.get("follow_selection_after_edit", True))
            self.follow_selection_checkbox.blockSignals(False)
            self.exclude_gestoppt_checkbox.blockSignals(True)
            self.exclude_gestoppt_checkbox.setChecked(config.get("exclude_gestoppt_from_stats", False))
            self.exclude_gestoppt_checkbox.blockSignals(False)
            self.model.colors_enabled = config.get_dict("colors_enabled")
            for key, action in self._color_actions.items():
                action.blockSignals(True)
                action.setChecked(self.model.colors_enabled.get(key, True))
                action.blockSignals(False)
            self.refresh()

    def _reset_filters(self):
        self.verlag_filter.setCurrentIndex(0)
        self.voe1_filter.setCurrentIndex(0)
        self.search_input.clear()

    def _refresh_verlag_filter_options(self):
        current = self.verlag_filter.currentText() if self.verlag_filter.count() else "Alle"
        self.verlag_filter.blockSignals(True)
        self.verlag_filter.clear()
        self.verlag_filter.addItem("Alle")
        self.verlag_filter.addItems(self._distinct_values("verlag"))
        index = self.verlag_filter.findText(current)
        self.verlag_filter.setCurrentIndex(index if index >= 0 else 0)
        self.verlag_filter.blockSignals(False)

    @staticmethod
    def _vline():
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    @staticmethod
    def _swatch(color):
        lbl = QLabel()
        lbl.setFixedSize(14, 14)
        lbl.setStyleSheet(f"background-color: {color}; border: 1px solid #888;")
        return lbl

    def _build_footer_legend(self):
        """VÖ+1-/Komplett-Beendet-Farblegende als dauerhaft sichtbarer
        Bereich der Statuszeile (rechts, bleibt unabhängig von normalen
        Statusmeldungen wie "Gespeichert" sichtbar)."""
        legend = QWidget()
        row = QHBoxLayout(legend)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel("VÖ +1:"))
        for label, color in (
            ("Beendet", colors.VOE1_STATUS_COLORS["beendet"]),
            ("TBA", colors.VOE1_STATUS_COLORS["tba"]),
            ("Gestoppt", colors.VOE1_STATUS_COLORS["gestoppt"]),
            ("NA", colors.VOE1_STATUS_COLORS["na"]),
        ):
            row.addSpacing(6)
            row.addWidget(self._swatch(color))
            row.addWidget(QLabel(label))

        row.addSpacing(12)
        row.addWidget(QLabel("Komplett/Beendet:"))
        row.addSpacing(6)
        row.addWidget(self._swatch(colors.JA_NEIN_COLORS["ja"]))
        row.addWidget(QLabel("Ja"))
        row.addSpacing(6)
        row.addWidget(self._swatch(colors.JA_NEIN_COLORS["nein"]))
        row.addWidget(QLabel("Nein"))

        row.addSpacing(12)
        row.addWidget(QLabel("Verlag: automatische Farbe je Verlag"))

        self.statusBar().addPermanentWidget(legend)

    # ------------------------------------------------------------ Seitenleiste

    def _build_sidebar(self, splitter):
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(4, 0, 0, 0)

        self._build_stats_section(layout)
        self._build_counts_section(layout)
        self._build_releases_section(layout)
        self._build_live_log_section(layout)

        splitter.addWidget(sidebar)
        splitter.setStretchFactor(1, 0)  # die Seitenleiste behält ihre Breite beim Vergrößern des Fensters

    def _build_stats_section(self, layout):
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        box_layout = QVBoxLayout(box)
        self.stat_besitz_lbl = self._stat_field(box_layout, "Summe im Besitz:")
        self.stat_gelesen_lbl = self._stat_field(box_layout, "Summe gelesen:")
        self.stat_diff_lbl = self._stat_field(box_layout, "Differenz (Besitz − gelesen):")
        self.stat_percent_lbl = self._stat_field(box_layout, "Gelesen-Anteil:")
        layout.addWidget(box)

    @staticmethod
    def _stat_field(parent_layout, label_text):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)
        value_lbl = QLabel("0")
        value_lbl.setStyleSheet("font-weight: bold;")
        row.addWidget(value_lbl)
        parent_layout.addLayout(row)
        return value_lbl

    def _stats_entries(self):
        """Liefert die Einträge, die in Summen-/Bilanz-Berechnungen
        einfließen (Statistik-Box, Typ-Bilanz) - respektiert die Option
        "Gestoppt: keine Berechnung" (VÖ +1 = "Gestoppt" wird dann
        ausgeschlossen). Reine Anzahl-Auflistungen (Verlag) sind davon
        NICHT betroffen."""
        if getattr(self, "exclude_gestoppt_checkbox", None) and self.exclude_gestoppt_checkbox.isChecked():
            return [e for e in self.data if (e.get("voe_1") or "").strip().lower() != "gestoppt"]
        return self.data

    def _update_stats(self):
        sum_besitz = 0
        sum_gelesen = 0
        for entry in self._stats_entries():
            try:
                sum_besitz += int((entry.get("baende_bis") or "").strip())
            except ValueError:
                pass
            try:
                sum_gelesen += int((entry.get("gelesen_bis") or "").strip())
            except ValueError:
                pass

        diff = sum_besitz - sum_gelesen
        percent = (sum_gelesen / sum_besitz * 100) if sum_besitz else 0.0

        self.stat_besitz_lbl.setText(str(sum_besitz))
        self.stat_gelesen_lbl.setText(str(sum_gelesen))
        self.stat_diff_lbl.setText(str(diff))
        self.stat_percent_lbl.setText(f"{percent:.1f} %")

    def _build_counts_section(self, layout):
        layout.addWidget(QLabel("<b>Anzahl nach Verlag</b>"))
        self.verlag_counts_list = QListWidget()
        self.verlag_counts_list.setAlternatingRowColors(True)
        layout.addWidget(self.verlag_counts_list, 1)

        layout.addWidget(QLabel("<b>Anzahl nach Typ</b>"))
        typ_comment = QLabel("<i>Gesamt / Gelesen / Offen</i>")
        typ_comment.setStyleSheet("color: #666;")
        layout.addWidget(typ_comment)
        self.typ_counts_list = QListWidget()
        self.typ_counts_list.setAlternatingRowColors(True)
        self.typ_counts_list.setMaximumHeight(110)
        self.typ_counts_list.setToolTip(
            "Gesamt = Summe „Bände (bis)“, Gelesen = Summe „Gelesen bis“, "
            "Offen = Gesamt − Gelesen, jeweils je Typ (in dieser Reihenfolge)."
        )
        layout.addWidget(self.typ_counts_list)

    def _update_counts(self):
        """Aktualisiert die Verlags-/Typ-Auflistung in der Seitenleiste -
        passt sich dynamisch an, sobald neue Verlage/Typen im Bestand
        auftauchen oder verschwinden."""
        self._fill_count_list(self.verlag_counts_list, "verlag")
        self._fill_typ_counts()

    def _fill_typ_counts(self):
        """Anzahl nach Typ, erweitert um die Bände-Bilanz je Typ (Gesamt/
        Gelesen/Offen) - respektiert die Option "Gestoppt nicht in
        Berechnung einbeziehen", falls aktiv."""
        entries = self._stats_entries()
        stats_by_typ = {}
        for entry in entries:
            typ = (entry.get("typ") or "").strip()
            if not typ:
                continue
            try:
                besitz = int((entry.get("baende_bis") or "").strip())
            except ValueError:
                besitz = 0
            try:
                gelesen = int((entry.get("gelesen_bis") or "").strip())
            except ValueError:
                gelesen = 0
            bucket = stats_by_typ.setdefault(typ, {"gesamt": 0, "gelesen": 0})
            bucket["gesamt"] += besitz
            bucket["gelesen"] += gelesen

        self.typ_counts_list.clear()
        for typ, bucket in sorted(stats_by_typ.items(), key=lambda kv: (-kv[1]["gesamt"], kv[0].lower())):
            offen = bucket["gesamt"] - bucket["gelesen"]
            self.typ_counts_list.addItem(f"{typ}: {bucket['gesamt']} · {bucket['gelesen']} · {offen}")

    def _fill_count_list(self, list_widget, column):
        counts = {}
        for entry in self.data:
            value = (entry.get(column) or "").strip()
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1

        current_selection = list_widget.currentItem().text() if list_widget.currentItem() else None
        list_widget.clear()
        for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())):
            list_widget.addItem(f"{value}  ({count})")

        if current_selection is not None:
            matches = list_widget.findItems(current_selection, Qt.MatchStartsWith)
            if matches:
                list_widget.setCurrentItem(matches[0])

    def _build_releases_section(self, layout):
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        box_layout = QVBoxLayout(box)

        box_layout.addWidget(QLabel("<b>Erscheinungstermine</b>"))
        self.release_current_lbl = self._stat_field(box_layout, "Aktueller Monat:")
        self.release_plus1_lbl = self._stat_field(box_layout, "Nächster Monat:")
        self.release_plus2_lbl = self._stat_field(box_layout, "Übernächster Monat:")

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        box_layout.addWidget(divider)

        box_layout.addWidget(QLabel("<b>Ausstehende Termine</b>"))
        self.overdue_count_lbl = self._stat_field(box_layout, "Vor aktuellem Monat:")

        box.setToolTip(
            "Zählt Termine (Treffer über alle fünf VÖ-Spalten VÖ +1 … VÖ +5), nicht "
            "eindeutige Titel - ein Titel mit zwei Terminen im selben Zeitraum zählt "
            "also zweimal.\n"
            "„Ausstehende Termine“ = vermutlich bereits erschienen, aber „Bände (bis)“ "
            "noch nicht per „+1“ nachgetragen."
        )
        layout.addWidget(box)

    def _update_releases(self):
        """Aktualisiert die Zähler "Erscheinende Bücher" (aktueller Monat,
        +1, +2 - über alle VÖ-Spalten) und "Ausstehend" (VÖ-Termin vor dem
        aktuellen Monat) in der Seitenleiste."""
        today = date.today()
        upcoming_months = []
        y, m = today.year, today.month
        for _ in range(3):
            upcoming_months.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1

        counts = [0, 0, 0]
        overdue_count = 0
        for entry in self.data:
            for _col, parsed in _entry_voe_dates(entry):
                key = (parsed.year, parsed.month)
                if key in upcoming_months:
                    counts[upcoming_months.index(key)] += 1
                elif key < (today.year, today.month):
                    overdue_count += 1

        self.release_current_lbl.setText(str(counts[0]))
        self.release_plus1_lbl.setText(str(counts[1]))
        self.release_plus2_lbl.setText(str(counts[2]))
        self.overdue_count_lbl.setText(str(overdue_count))

    def _build_live_log_section(self, layout):
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Live-Log (diese Sitzung)</b>"))
        header.addStretch(1)
        layout.addLayout(header)

        self.live_log_view = QPlainTextEdit()
        self.live_log_view.setReadOnly(True)
        self.live_log_view.setPlaceholderText("Änderungen erscheinen hier, sobald sie passieren …")
        self.live_log_view.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout.addWidget(self.live_log_view, 2)

    def _build_table(self, splitter):
        self.model = MangaTableModel(DISPLAY_COLUMNS, DISPLAY_LABELS)
        self.delegate = CellDelegate(
            DISPLAY_COLUMNS,
            on_increment_baende=self._increment_baende,
            on_increment_gelesen=self._increment_gelesen,
        )

        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(self.delegate)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(False)  # Zebra kommt aus dem Modell (Qt.BackgroundRole)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(26)
        self.view.horizontalHeader().setSectionsClickable(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().sectionClicked.connect(self._sort_by_index)
        self.view.doubleClicked.connect(self._on_double_clicked)
        self.view.selectionModel().selectionChanged.connect(self._on_selection_changed)

        for col_idx, col in enumerate(DISPLAY_COLUMNS):
            self.view.setColumnWidth(col_idx, COL_DEFAULT_WIDTHS.get(col, 100))

        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 1)  # die Tabelle bekommt zusätzlichen Platz beim Vergrößern des Fensters

    def _autosize_titel_column(self):
        """Passt die Breite der Spalte "Titel" automatisch an den längsten
        aktuell vorhandenen Titel der GESAMTEN Sammlung an (nicht nur die
        gerade gefilterte Ansicht, damit die Breite beim Filtern/Suchen
        nicht ständig hin- und herspringt) - keine feste Breite, reagiert
        auf neue/geänderte/gelöschte Titel."""
        col_idx = DISPLAY_COLUMNS.index("titel")
        fm = self.view.fontMetrics()
        longest = max((fm.horizontalAdvance(e.get("titel") or "") for e in self.data), default=0)
        width = max(COL_DEFAULT_WIDTHS["titel"], longest + 24)  # etwas Innenabstand
        self.view.setColumnWidth(col_idx, width)

    # --------------------------------------------------------------- Daten

    def _filtered_sorted_data(self):
        search = self.search_input.text().strip().lower()
        verlag_filter = self.verlag_filter.currentText() if self.verlag_filter.count() else "Alle"
        voe1_filter = self.voe1_filter.currentText() if self.voe1_filter.count() else "Alle"

        rows = self.data
        if search:
            rows = [e for e in rows if any(search in (e.get(c) or "").lower() for c in db.COLUMN_NAMES)]
        if verlag_filter and verlag_filter != "Alle":
            rows = [e for e in rows if (e.get("verlag") or "").strip() == verlag_filter]
        if voe1_filter and voe1_filter != "Alle":
            wanted_category = voe1_filter.lower() if voe1_filter != "Mit Datum" else "datum"
            rows = [e for e in rows if _voe1_category(e.get("voe_1")) == wanted_category]

        rows = list(rows)
        if self.sort_column == RUCKSTAND_COLUMN:
            def _key(e):
                v = _ruckstand_value(e)
                return (v is None, v if v is not None else 0)
            rows.sort(key=_key, reverse=self.sort_reverse)
        else:
            rows.sort(key=lambda e: sorting.sort_key(self.sort_column, e.get(self.sort_column)), reverse=self.sort_reverse)
        return rows

    def refresh(self):
        self._refresh_verlag_filter_options()
        colors.set_verlag_universe(self._distinct_values("verlag"))
        self._update_stats()
        self._update_counts()
        self._update_releases()
        rows = self._filtered_sorted_data()

        follow_selection = self.follow_selection_checkbox.isChecked()
        scroll_value = None
        if not follow_selection:
            scroll_value = self.view.verticalScrollBar().value()

        selected_id = self.selected_row_id
        self.model.set_rows(rows)

        if selected_id is not None:
            for row_index, entry in enumerate(rows):
                if entry["id"] == selected_id:
                    self.view.selectRow(row_index)
                    break
            else:
                self.selected_row_id = None

        if scroll_value is not None:
            # Ansicht bewusst NICHT dem (neu sortierten) Eintrag hinterher-
            # springen lassen, sondern die vorherige Scroll-Position beibehalten.
            self.view.verticalScrollBar().setValue(scroll_value)

        status = f"{len(rows)} Einträge"
        if self.dirty:
            status += "  —  ungespeicherte Änderungen"
        self.statusBar().showMessage(status)

    def _selected_id(self):
        sel = self.view.selectionModel().selectedRows()
        if not sel:
            return None
        return self.model.data(sel[0], ROW_ID_ROLE)

    def _on_double_clicked(self, index):
        # Doppelklick auf "Bände (bis)"/"Gelesen bis" soll NICHT den
        # Bearbeiten-Dialog öffnen - dort sitzt der "+1"-Button, ein
        # Doppelklick darauf ist naheliegend und würde sonst ungewollt
        # zusätzlich das Formular aufreißen.
        col = DISPLAY_COLUMNS[index.column()]
        if col in INCREMENTABLE_COLUMNS:
            return
        self.edit_selected()

    def _on_selection_changed(self, *_args):
        self.selected_row_id = self._selected_id()

    def _sort_by_index(self, col_index):
        column = DISPLAY_COLUMNS[col_index]
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh()

    # ------------------------------------------------------------ Aktionen

    def open_add_dialog(self):
        dlg = EntryDialog(self, "Neuer Eintrag", on_save=self._add_entry, verlag_values=self._distinct_values("verlag"))
        dlg.exec()

    def edit_selected(self):
        row_id = self._selected_id()
        if row_id is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst einen Eintrag auswählen.")
            return
        entry = self._find_entry(row_id)
        if entry is None:
            return
        dlg = EntryDialog(
            self, "Eintrag bearbeiten", initial=entry,
            on_save=lambda v: self._update_entry(row_id, v),
            verlag_values=self._distinct_values("verlag"),
        )
        dlg.exec()

    def delete_selected(self):
        row_id = self._selected_id()
        if row_id is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst einen Eintrag auswählen.")
            return
        entry = self._find_entry(row_id)
        if entry is None:
            return
        answer = QMessageBox.question(
            self, "Löschen bestätigen", f"„{entry['titel']}“ wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._push_undo_snapshot()
            self.data = [e for e in self.data if e["id"] != row_id]
            self._mark_dirty()
            self._commit_pending_action()
            self._autosize_titel_column()
            self.refresh()
            self._log(f"Gelöscht: „{entry['titel']}“.")

    def _add_entry(self, values):
        self._push_undo_snapshot()
        values["id"] = self.next_temp_id
        self.next_temp_id -= 1
        self.data.append(values)
        self.selected_row_id = values["id"]
        self._mark_dirty()
        self._commit_pending_action()
        self._autosize_titel_column()
        self.refresh()
        self._log(f"Neuer Eintrag: „{values.get('titel') or '(ohne Titel)'}“.")

    def _update_entry(self, row_id, values):
        entry = self._find_entry(row_id)
        if entry is None:
            return
        self._push_undo_snapshot()
        entry.update(values)
        self.selected_row_id = row_id
        self._mark_dirty()
        self._commit_pending_action()
        self._autosize_titel_column()
        self.refresh()
        self._log(f"Bearbeitet: „{entry.get('titel') or '(ohne Titel)'}“.")

    def _increment_baende(self, row_id):
        entry = self._find_entry(row_id)
        if entry is None:
            return
        self._push_undo_snapshot()
        new_value = logic.increment_baende(entry)
        if new_value is None:
            self._discard_pending_snapshot()
            QMessageBox.warning(self, "Hinweis", "„Bände (bis)“ enthält keine gültige Zahl.")
            return
        self.selected_row_id = row_id
        self._mark_dirty()
        self._commit_pending_action()
        self.refresh()
        self._log(f"„{entry.get('titel')}“: Bände (bis) auf {new_value} erhöht.")

    def _increment_gelesen(self, row_id):
        entry = self._find_entry(row_id)
        if entry is None:
            return
        self._push_undo_snapshot()
        result = logic.increment_gelesen(entry)
        if result is None:
            self._discard_pending_snapshot()
            QMessageBox.warning(self, "Hinweis", "„Gelesen bis“ enthält keine gültige Zahl.")
            return
        if result == logic.EXCEEDS:
            self._discard_pending_snapshot()
            QMessageBox.information(
                self, "Hinweis",
                "„Gelesen bis“ kann nicht über „Bände (bis)“ hinaus erhöht werden – "
                "du kannst nicht mehr Bände gelesen haben, als du besitzt.",
            )
            return
        self.selected_row_id = row_id
        self._mark_dirty()
        self._commit_pending_action()
        self.refresh()
        self._log(f"„{entry.get('titel')}“: Gelesen bis auf {result} erhöht.")

    def import_csv_dialog(self):
        path, _filter = QFileDialog.getOpenFileName(self, "CSV-Datei auswählen", "", "CSV-Dateien (*.csv)")
        if not path:
            return

        try:
            parsed_entries, warnings = import_csv.parse_csv(path)
        except ValueError as exc:
            QMessageBox.critical(self, "CSV-Import", f"Import abgebrochen:\n\n{exc}")
            return

        existing_titles = {(e.get("titel") or "").strip().lower() for e in self.data}
        imported, skipped = 0, 0
        if parsed_entries:
            self._push_undo_snapshot()
        for parsed in parsed_entries:
            title_key = parsed["titel"].strip().lower()
            if title_key in existing_titles:
                skipped += 1
                continue
            parsed["id"] = self.next_temp_id
            self.next_temp_id -= 1
            self.data.append(parsed)
            existing_titles.add(title_key)
            imported += 1

        if imported:
            self._mark_dirty()
            self._commit_pending_action()
            self._autosize_titel_column()
            self._log(f"CSV-Import: {imported} neu importiert, {skipped} übersprungen ({path}).")
        elif parsed_entries:
            self._discard_pending_snapshot()  # nichts importiert -> Snapshot wieder verwerfen

        self.refresh()

        message = (
            f"{imported} neu importiert, {skipped} übersprungen (bereits vorhanden).\n"
            "Die Einträge sind noch nicht gespeichert – bitte auf „💾 Speichern“ klicken."
        )
        if warnings:
            message += "\n\n" + "\n".join(warnings)
        QMessageBox.information(self, "Import", message)

    def export_csv_dialog(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, "CSV-Export speichern unter", "manga_library_export.csv", "CSV-Dateien (*.csv)"
        )
        if not path:
            return
        try:
            count = csv_export.export_csv(path, self.data)
        except OSError as exc:
            QMessageBox.critical(self, "CSV-Export", f"Export fehlgeschlagen:\n\n{exc}")
            return
        QMessageBox.information(self, "CSV-Export", f"{count} Einträge wurden exportiert nach:\n{path}")

    def drive_upload(self):
        if self.dirty:
            answer = QMessageBox.question(
                self, "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Änderungen. Diese müssen zuerst lokal gespeichert werden, "
                "bevor zu Google Drive gesichert werden kann. Jetzt speichern und fortfahren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            self.save()

        try:
            import drive_sync
            self.statusBar().showMessage("Sichere zu Google Drive ...")
            QApplication.processEvents()
            drive_sync.upload()
            QMessageBox.information(self, "Google Drive", "Datenbank wurde erfolgreich zu Google Drive gesichert.")
        except Exception as exc:  # noqa: BLE001 - dem Nutzer die Ursache zeigen
            QMessageBox.critical(self, "Google Drive", str(exc))
        finally:
            self.refresh()

    def drive_download(self):
        warning = "Die lokale Datenbank wird durch die Version aus Google Drive ersetzt. Fortfahren?"
        if self.dirty:
            warning = "Ungespeicherte Änderungen gehen dabei verloren!\n\n" + warning
        answer = QMessageBox.question(
            self, "Google Drive", warning, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        try:
            import drive_sync
            self.statusBar().showMessage("Lade von Google Drive ...")
            QApplication.processEvents()
            drive_sync.download()
            self.data = db.load_all()
            self._clean_snapshot = copy.deepcopy(self.data)
            self.dirty = False
            self.undo_stack.clear()
            self.redo_stack.clear()
            self._update_undo_redo_actions()
            self._update_title()
            self._autosize_titel_column()
            QMessageBox.information(self, "Google Drive", "Datenbank wurde erfolgreich von Google Drive geladen.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Google Drive", str(exc))
        finally:
            self.refresh()

    # ------------------------------------------------------ ISBN-Abgleich

    def open_isbn_lookup_dialog(self):
        dlg = IsbnLookupDialog(self, on_submit=self._start_isbn_lookup)
        dlg.exec()

    def _start_isbn_lookup(self, selection):
        # selection ist ("month", monat, jahr, overwrite) oder ("status", "TBA"/"NA", overwrite)
        kind = selection[0]
        if kind == "month":
            _, month, year, overwrite = selection
            label = f"{month:02d}/{year}"
            only_month, only_status = (month, year), None
        else:
            _, status, overwrite = selection
            label = f"VÖ +1 = {status}"
            only_month, only_status = None, status
        if overwrite:
            label += " (inkl. bereits vorhandener ISBNs)"

        # Der Abgleich liest/schreibt direkt in der Datenbankdatei, nicht im
        # Puffer - ungespeicherte Änderungen müssten sonst ignoriert werden.
        if self.dirty:
            answer = QMessageBox.question(
                self, "Ungespeicherte Änderungen",
                "Der ISBN-Abgleich arbeitet direkt auf der gespeicherten Datenbank. "
                "Ungespeicherte Änderungen müssen dafür zuerst gespeichert werden. "
                "Jetzt speichern und fortfahren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            self.save()

        try:
            import isbn_lookup
        except ImportError:
            QMessageBox.critical(
                self, "ISBN-Abgleich",
                "Das Paket „requests“ wird dafür benötigt.\n\nBitte installieren mit:\npip install requests",
            )
            return

        progress = QProgressDialog(
            f"Suche ISBNs für {label} ...\nDas kann je nach Anzahl der Titel ein bis zwei Minuten dauern.",
            None, 0, 0, self,
        )
        progress.setWindowTitle("ISBN-Abgleich läuft ...")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        signals = IsbnWorkerSignals()
        signals.finished.connect(lambda report, bestellliste, error: self._finish_isbn_lookup(
            progress, label, report, bestellliste, error
        ))

        def worker():
            report = None
            bestellliste = None
            error = None
            try:
                db_path = str(db.DB_FILE)
                report = isbn_lookup.fill_missing_isbns(
                    db_path, only_month=only_month, only_status=only_status, overwrite=overwrite
                )
                if kind == "month":
                    bestellliste = isbn_lookup.bestellliste_markdown(db_path, month, year)
                else:
                    bestellliste = isbn_lookup.bestellliste_markdown(db_path, status=status)
            except Exception as exc:  # noqa: BLE001 - dem Nutzer die Ursache zeigen
                error = str(exc)
            signals.finished.emit(report, bestellliste, error)

        self._isbn_signals = signals  # Referenz halten, damit Qt sie nicht vorzeitig einsammelt
        threading.Thread(target=worker, daemon=True).start()

    def _finish_isbn_lookup(self, progress, label, report, bestellliste, error):
        progress.close()

        # Anders als früher: der ISBN-Abgleich schreibt seit der
        # isbn_cache-Tabelle nichts mehr in `werke` - der Zwischenspeicher
        # (Puffer, Undo/Redo, "ungespeicherte Änderungen") ist von einem
        # Abgleich also gar nicht betroffen und muss weder neu geladen
        # noch zurückgesetzt werden.

        if error:
            QMessageBox.critical(self, "ISBN-Abgleich", f"Fehler beim Abgleich:\n\n{error}")
            return

        win = IsbnResultWindow(self, label, report, bestellliste)
        win.exec()
