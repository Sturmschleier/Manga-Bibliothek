"""
gui/main_window.py
Hauptfenster (MangaLibraryApp): Menüleiste, Toolbar, Filter, Tabelle,
Seitenleiste, Live-Log sowie die Steuerung von Speichern, Import/Export,
Google Drive, Bestell-Mails und ISBN-Abgleich.

Wichtig: Alle Änderungen (neuer Eintrag, Bearbeiten, Löschen, +1-Buttons,
CSV-Import) wirken zunächst nur auf den Zwischenspeicher (self.buffer, siehe
library.LibraryBuffer - dort liegt auch Rückgängig/Wiederholen).
Erst ein Klick auf "💾 Speichern" schreibt den kompletten Bestand in die
lokale Datenbank. Solange ungespeicherte Änderungen bestehen, zeigen
Fenstertitel und Statuszeile das deutlich an; beim Schließen des Fensters
und vor einem Google-Drive-Upload wird ebenfalls nachgefragt.

Die Tabelle nutzt QTableView + ein eigenes QAbstractTableModel: Qt erzeugt
dabei nur für die aktuell sichtbaren Zeilen tatsächlich Zeichen-/Klick-
Aufwand ("virtualisiert") - unabhängig von der Gesamtgröße der Sammlung.
"""

import copy
import csv
import os
import threading
from datetime import date

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
    QInputDialog, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSizePolicy,
    QSplitter, QTableView, QVBoxLayout, QWidget,
)

import changelog
import colors
import config
import csv_export
import database as db
import import_csv
import logic
import mail_fetch
import order_mail
import sorting
from library import LibraryBuffer

from .constants import (
    APP_TITLE, COL_DEFAULT_WIDTHS, DISPLAY_COLUMNS, DISPLAY_LABELS,
    INCREMENTABLE_COLUMNS, ROW_ID_ROLE, RUCKSTAND_COLUMN,
    VOE1_FILTER_OPTIONS, _entry_voe_dates, _ruckstand_value, _voe1_category,
)
from .dialogs import ConfigDialog, EntryDialog, IsbnLookupDialog
from .isbn_view import IsbnResultWindow
from .mail_dialogs import MailSelectDialog, MailSettingsDialog
from .table import CellDelegate, MangaTableModel
from .worker import AsyncCall

SEARCH_DELAY_MS = 200  # Suche erst nach kurzer Tipp-Pause auswerten

class MangaLibraryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1450, 780)

        config_problem = config.problem()   # beschädigte config.json -> Hinweis nach dem Start
        config.ensure_file_exists()
        changelog.archive_old_entries()
        changelog.prune_isbn_logs()
        changelog.prune_order_logs()

        db.init_db()

        self.buffer = LibraryBuffer(db.load_all())   # Zwischenspeicher bis "Speichern"

        self.sort_column = "titel"
        self.sort_reverse = False
        self.selected_row_id = None
        self._mail_session_passwords = {}  # nur im Arbeitsspeicher, nie auf Platte
        self._mail_call = None
        self._drive_call = None
        self._isbn_call = None
        self.setAcceptDrops(True)  # .eml-Dateien per Drag & Drop einlesen

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        self._build_menu_bar()
        self._build_toolbar(root)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self._build_table(self.main_splitter)
        self._build_sidebar(self.main_splitter)
        root.addWidget(self.main_splitter, 1)
        self._sidebar_sized = False

        self.statusBar()  # QMainWindow-eigene Statuszeile aktivieren
        self._build_footer_legend()

        self._autosize_titel_column()  # einmalig für den initial geladenen Bestand
        self.refresh()

        if config_problem:
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                self, "Konfiguration",
                f"Die Datei config.json ist beschädigt ({config_problem}).\n\n"
                "Es gelten vorerst die Standardwerte. Sobald eine Einstellung geändert wird, "
                "wird die beschädigte Datei als config.json.defekt aufbewahrt.",
            ))

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


    @property
    def data(self):
        """Die Einträge im Zwischenspeicher (siehe library.LibraryBuffer)."""
        return self.buffer.data

    @property
    def dirty(self) -> bool:
        return self.buffer.dirty

    def _after_change(self, autosize: bool = False):
        """Nach jeder Änderung am Zwischenspeicher: Fenstertitel ("*"),
        Rückgängig-/Wiederholen-Knöpfe und Anzeige aktualisieren."""
        self._update_title()
        self._update_undo_redo_actions()
        if autosize:
            self._autosize_titel_column()
        self.refresh()

    def _update_title(self):
        self.setWindowTitle(APP_TITLE + (" *" if self.dirty else ""))

    def _find_entry(self, row_id):
        return self.buffer.find(row_id)

    def _distinct_values(self, column):
        return self.buffer.distinct_values(column)

    # ------------------------------------------------------- Undo/Redo

    def _update_undo_redo_actions(self):
        self.undo_btn.setEnabled(self.buffer.can_undo)
        self.redo_btn.setEnabled(self.buffer.can_redo)

    def undo(self):
        if not self.buffer.undo():
            return
        self.selected_row_id = None
        self._after_change(autosize=True)
        self.statusBar().showMessage("Rückgängig gemacht.", 3000)
        self._log("Rückgängig gemacht.")

    def redo(self):
        if not self.buffer.redo():
            return
        self.selected_row_id = None
        self._after_change(autosize=True)
        self.statusBar().showMessage("Wiederholt.", 3000)
        self._log("Wiederholt.")

    def save(self) -> bool:
        """Schreibt den kompletten Puffer in die Datenbank. Vorher wird der
        bisherige Stand der Datenbankdatei nach BACKUP/ gesichert (siehe
        database.create_backup).

        Gibt True zurück, wenn gespeichert wurde. Bei einem Fehler (z.B.
        Datei von Cloud-Synchronisierung oder Virenscanner gesperrt,
        Datenträger voll) erscheint eine Meldung und es wird False
        zurückgegeben - der Puffer bleibt dann unverändert erhalten, nichts
        geht verloren."""
        count = len(self.data)
        try:
            db.create_backup("vor-speichern")
        except Exception as exc:  # noqa: BLE001 - dem Nutzer die Ursache zeigen
            answer = QMessageBox.warning(
                self, "Sicherung fehlgeschlagen",
                f"Vor dem Speichern konnte keine Sicherung der Datenbank angelegt werden:\n\n{exc}\n\n"
                "Trotzdem speichern?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
        try:
            saved = db.replace_all(self.data)
        except Exception as exc:  # noqa: BLE001 - ein Speicherfehler darf die Änderungen nicht verschlucken
            self._log(f"Speichern fehlgeschlagen: {exc}")
            QMessageBox.critical(
                self, "Speichern fehlgeschlagen",
                f"Die Datenbank konnte nicht gespeichert werden:\n\n{exc}\n\n"
                "Die Änderungen sind weiterhin im Zwischenspeicher. Mögliche Ursache: Die Datei ist "
                "gerade von einem anderen Programm gesperrt (z. B. Cloud-Synchronisierung oder "
                "Virenscanner). Bitte später erneut speichern.",
            )
            return False
        self.buffer.mark_saved(saved)
        self.selected_row_id = None
        self._update_title()
        self.refresh()
        self.statusBar().showMessage(f"Gespeichert – {len(self.data)} Einträge", 5000)
        self._log(f"Gespeichert ({count} Einträge).")
        return True

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
        if answer == QMessageBox.Yes and not self.save():
            # Speichern fehlgeschlagen: Fenster offen lassen, sonst wären die
            # Änderungen weg (ein QCloseEvent gilt standardmäßig als akzeptiert).
            event.ignore()
            return
        event.accept()

    # ------------------------------------------------------------------ UI

    def _build_menu_bar(self):
        """Menüleiste: "Datei" (Eintrags-Verwaltung, CSV-Import/-Export,
        Google-Drive-Download) und "Konfigurieren" (Farbcodierung,
        Konfiguration, Anzeige-/Berechnungsoptionen)."""
        file_menu = self.menuBar().addMenu("&Datei")

        add_action = file_menu.addAction("Neuer Eintrag")
        add_action.setShortcut(QKeySequence.New)
        add_action.triggered.connect(self.open_add_dialog)

        edit_action = file_menu.addAction("Bearbeiten")
        edit_action.triggered.connect(self.edit_selected)

        delete_action = file_menu.addAction("Löschen")
        delete_action.triggered.connect(self.delete_selected)

        file_menu.addSeparator()

        search_action = file_menu.addAction("Bei buchhandel.de suchen")
        search_action.setShortcut(QKeySequence("Ctrl+B"))
        search_action.setToolTip("Den markierten Titel direkt auf buchhandel.de suchen (öffnet den Browser)")
        search_action.triggered.connect(self.search_selected_on_buchhandel)

        file_menu.addSeparator()

        import_action = file_menu.addAction("CSV importieren …")
        import_action.triggered.connect(self.import_csv_dialog)

        export_action = file_menu.addAction("CSV exportieren …")
        export_action.triggered.connect(self.export_csv_dialog)

        order_action = file_menu.addAction("Bestellung aus E-Mail (.eml) einlesen …")
        order_action.setToolTip(
            "Liest eine Bestellbestätigung (.eml) und markiert die bestellten Titel hellblau. "
            "Die E-Mail selbst wird nicht gespeichert."
        )
        order_action.triggered.connect(self.import_order_mail_dialog)

        mailbox_action = file_menu.addAction("Bestellungen aus Postfach abrufen …")
        mailbox_action.setToolTip(
            "Ruft Bestellbestätigungen per IMAP direkt aus dem E-Mail-Postfach ab "
            "(Zugang unter Konfigurieren → Postfach). Es wird nichts im Postfach verändert."
        )
        mailbox_action.triggered.connect(self.fetch_orders_from_mailbox)

        file_menu.addSeparator()

        download_action = file_menu.addAction("Von Google Drive laden")
        download_action.triggered.connect(self.drive_download)

        config_menu = self.menuBar().addMenu("&Konfigurieren")

        self._build_colors_submenu(config_menu)

        config_action = config_menu.addAction("Konfiguration …")
        config_action.setToolTip("Zentrale Konfigurationsdatei (config.json) bearbeiten")
        config_action.triggered.connect(self.open_config_dialog)

        mail_settings_action = config_menu.addAction("Postfach (IMAP) …")
        mail_settings_action.setToolTip("Zugang und Suchfilter für den Abruf von Bestellbestätigungen")
        mail_settings_action.triggered.connect(self.open_mail_settings_dialog)

        config_menu.addSeparator()

        self.follow_selection_action = config_menu.addAction("Nach Bearbeitung zur Zeile springen")
        self.follow_selection_action.setCheckable(True)
        self.follow_selection_action.setChecked(config.get_bool("follow_selection_after_edit"))
        self.follow_selection_action.setToolTip(
            "Wenn aktiv: springt die Ansicht nach dem Bearbeiten/Sortieren automatisch zum "
            "bearbeiteten Eintrag. Wenn deaktiviert: die aktuelle Scroll-Position bleibt erhalten.\n"
            "Der Wert wird dauerhaft in der Konfigurationsdatei gemerkt."
        )
        self.follow_selection_action.toggled.connect(
            lambda checked: config.set_value("follow_selection_after_edit", checked)
        )

        self.exclude_gestoppt_action = config_menu.addAction("Gestoppt: keine Berechnung")
        self.exclude_gestoppt_action.setCheckable(True)
        self.exclude_gestoppt_action.setChecked(config.get_bool("exclude_gestoppt_from_stats"))
        self.exclude_gestoppt_action.setToolTip(
            "Wenn aktiv: Titel mit VÖ +1 = „Gestoppt“ fließen nicht in die Statistik-Box "
            "und die Gesamt/Gelesen/Offen-Bilanz je Typ ein.\n"
            "Der Wert wird dauerhaft in der Konfigurationsdatei gemerkt."
        )
        self.exclude_gestoppt_action.toggled.connect(self._on_exclude_gestoppt_toggled)

    def _build_toolbar(self, root):
        bar = QHBoxLayout()

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
        self.save_btn.setShortcut(QKeySequence.Save)
        self.save_btn.setToolTip("Alle Änderungen dauerhaft in der Datenbank speichern (Strg+S)")
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)

        bar.addWidget(self._vline())

        upload_btn = QPushButton("⬆ Zu Google Drive sichern")
        upload_btn.clicked.connect(self.drive_upload)
        bar.addWidget(upload_btn)

        bar.addWidget(self._vline())

        isbn_btn = QPushButton("🔍 ISBN-Abgleich / Bestellliste")
        isbn_btn.clicked.connect(self.open_isbn_lookup_dialog)
        bar.addWidget(isbn_btn)

        bar.addWidget(self._vline())
        self._build_filter_bar(bar)

        bar.addStretch(1)
        root.addLayout(bar)

    def _build_colors_submenu(self, parent_menu):
        """
        Untermenü zum Ein-/Ausschalten der Farbcodierung je Kategorie
        (VÖ +1, Komplett/Beendet, Verlag) - schreibt weiterhin in
        config.json (colors_enabled), direkt aus der Oberfläche erreichbar,
        nicht nur per Hand-Bearbeiten der Konfigurationsdatei.
        """
        menu = parent_menu.addMenu("Farben")
        menu.setToolTip("Farbcodierung je Kategorie ein-/ausschalten (dauerhaft gespeichert)")

        self._color_actions = {}
        enabled = config.get_dict("colors_enabled")
        for key, label in (
            ("voe1", "VÖ +1 (Beendet/TBA/Gestoppt/NA)"),
            ("komplett_beendet", "Komplett/Beendet"),
            ("verlag", "Verlag"),
            ("bestellt", "Titel bestellt (hellblau)"),
            ("angekommen", "Titel angekommen (roter Balken links)"),
        ):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(enabled.get(key, True))
            action.toggled.connect(lambda checked, k=key: self._on_color_toggle(k, checked))
            self._color_actions[key] = action

    def _on_color_toggle(self, key, checked):
        cfg = config.load()
        colors_enabled = dict(cfg.get("colors_enabled") or {})
        colors_enabled[key] = checked
        config.set_value("colors_enabled", colors_enabled)
        self.model.colors_enabled = config.get_dict("colors_enabled")
        self.refresh()

    def _build_filter_bar(self, bar):
        bar.addWidget(QLabel("Verlag:"))
        self.verlag_filter = QComboBox()
        self.verlag_filter.setMinimumWidth(160)
        self.verlag_filter.currentIndexChanged.connect(lambda _i: self._refresh_table())
        bar.addWidget(self.verlag_filter)

        bar.addSpacing(16)
        bar.addWidget(QLabel("VÖ +1:"))
        self.voe1_filter = QComboBox()
        self.voe1_filter.addItems(VOE1_FILTER_OPTIONS)
        self.voe1_filter.setMinimumWidth(120)
        self.voe1_filter.currentIndexChanged.connect(lambda _i: self._refresh_table())
        bar.addWidget(self.voe1_filter)

        reset_btn = QPushButton("Filter zurücksetzen")
        reset_btn.clicked.connect(self._reset_filters)
        bar.addSpacing(16)
        bar.addWidget(reset_btn)

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
            self.follow_selection_action.blockSignals(True)
            self.follow_selection_action.setChecked(config.get_bool("follow_selection_after_edit"))
            self.follow_selection_action.blockSignals(False)
            self.exclude_gestoppt_action.blockSignals(True)
            self.exclude_gestoppt_action.setChecked(config.get_bool("exclude_gestoppt_from_stats"))
            self.exclude_gestoppt_action.blockSignals(False)
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

    @staticmethod
    def _bar_swatch(color):
        """Legenden-Feld für den Balken links (Balken in Farbe, Rest neutral)."""
        lbl = QLabel()
        lbl.setFixedSize(14, 14)
        lbl.setStyleSheet(f"background-color: #ffffff; border: 1px solid #888; border-left: 5px solid {color};")
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

        row.addSpacing(12)
        row.addWidget(self._swatch(colors.BESTELLT_COLOR))
        row.addWidget(QLabel("Titel bestellt"))
        row.addSpacing(6)
        row.addWidget(self._bar_swatch(colors.ANGEKOMMEN_COLOR))
        row.addWidget(QLabel("angekommen"))

        self.statusBar().addPermanentWidget(legend)

    # ------------------------------------------------------------ Seitenleiste

    def _build_sidebar(self, splitter):
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(4, 0, 0, 0)

        self._build_search_section(layout)
        self._build_stats_section(layout)
        self._build_counts_section(layout)
        self._build_releases_section(layout)
        self._build_live_log_section(layout)

        splitter.addWidget(sidebar)
        splitter.setStretchFactor(1, 0)  # die Seitenleiste behält ihre Breite beim Vergrößern des Fensters

    def _build_search_section(self, layout):
        row = QHBoxLayout()
        row.addWidget(QLabel("Suche:"))
        self.search_input = QLineEdit()
        self.search_input.setClearButtonEnabled(True)
        # Suche erst nach einer kurzen Tipp-Pause auswerten, nicht bei jedem Tastendruck
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._refresh_table)
        self.search_input.textChanged.connect(lambda _t: self._search_timer.start())
        row.addWidget(self.search_input, 1)
        layout.addLayout(row)

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
        if getattr(self, "exclude_gestoppt_action", None) and self.exclude_gestoppt_action.isChecked():
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
            "Zählt Termine (Treffer über alle drei VÖ-Spalten VÖ +1 … VÖ +3), nicht "
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
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_table_context_menu)
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
        """Alles neu anzeigen: Filterauswahl, Verlagsfarben, Seitenleiste und
        Tabelle - nach jeder Änderung am Bestand."""
        self._refresh_verlag_filter_options()
        colors.set_verlag_universe(self._distinct_values("verlag"))
        self._update_stats()
        self._update_counts()
        self._update_releases()
        self._refresh_table()

    def _refresh_table(self):
        """Nur die Tabelle neu filtern/sortieren (Suche, Filter, Sortierung) -
        die Seitenleiste hängt davon nicht ab."""
        rows = self._filtered_sorted_data()

        follow_selection = self.follow_selection_action.isChecked()
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
        self._refresh_table()

    # ------------------------------------------------------------ Aktionen

    def open_add_dialog(self):
        dlg = EntryDialog(
            self, "Neuer Eintrag", on_save=self._add_entry,
            verlag_values=self._distinct_values("verlag"), other_titles=self.buffer.titles_except(),
        )
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
            verlag_values=self._distinct_values("verlag"), other_titles=self.buffer.titles_except(row_id),
        )
        dlg.exec()

    def _show_table_context_menu(self, pos):
        """Rechtsklick auf eine Tabellenzeile: markiert die Zeile unter dem
        Mauszeiger und bietet die Aktionen für genau diesen Eintrag an."""
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        self.view.selectRow(index.row())

        menu = QMenu(self.view)
        menu.addAction("Bei buchhandel.de suchen", self.search_selected_on_buchhandel)
        entry = self._find_entry(self._selected_id())
        if entry is not None and (entry.get("bestellt") or entry.get("angekommen")):
            menu.addAction("Bestellt-/Angekommen-Markierung entfernen", self.clear_ordered_mark)
        menu.addSeparator()
        menu.addAction("Bearbeiten", self.edit_selected)
        menu.addAction("Löschen", self.delete_selected)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def clear_ordered_mark(self):
        """Entfernt die "bestellt"- (hellblau) und "angekommen"-Markierung
        (roter Balken) des markierten Eintrags von Hand (z. B. bei einer
        Fehlzuordnung oder Stornierung)."""
        entry = self._find_entry(self._selected_id())
        if entry is None or not (entry.get("bestellt") or entry.get("angekommen")):
            return
        entry = self.buffer.clear_marks(entry["id"])
        self._after_change()
        self._log(f"Bestellt-/Angekommen-Markierung entfernt: „{entry.get('titel')}“.")

    def search_selected_on_buchhandel(self):
        """Öffnet im Standardbrowser die buchhandel.de-Suche für den
        markierten Titel - unabhängig vom konfigurierten Fallback-Anbieter
        des ISBN-Abgleichs, direkt aus der Tabelle heraus."""
        row_id = self._selected_id()
        if row_id is None:
            QMessageBox.information(self, "Hinweis", "Bitte zuerst einen Eintrag auswählen.")
            return
        entry = self._find_entry(row_id)
        titel = (entry.get("titel") or "").strip() if entry else ""
        if not titel:
            return
        try:
            import isbn_lookup
        except ImportError:
            QMessageBox.critical(
                self, "buchhandel.de",
                "Das Paket „requests“ wird dafür benötigt.\n\nBitte installieren mit:\npip install requests",
            )
            return
        url = isbn_lookup.buchhandel_de_search_url(titel)
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "buchhandel.de", f"Der Browser konnte nicht geöffnet werden:\n\n{url}")
            return
        self.statusBar().showMessage(f"buchhandel.de: Suche nach „{titel}“ geöffnet.", 5000)

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
            self.buffer.delete(row_id)
            self._after_change(autosize=True)
            self._log(f"Gelöscht: „{entry['titel']}“.")

    def _add_entry(self, values):
        entry = self.buffer.add(values)
        self.selected_row_id = entry["id"]
        self._after_change(autosize=True)
        self._log(f"Neuer Eintrag: „{entry.get('titel') or '(ohne Titel)'}“.")

    def _update_entry(self, row_id, values):
        entry = self.buffer.update(row_id, values)   # erreichte Bestell-Markierungen entfallen dabei
        if entry is None:
            return
        self.selected_row_id = row_id
        self._after_change(autosize=True)
        self._log(f"Bearbeitet: „{entry.get('titel') or '(ohne Titel)'}“.")

    def _increment_baende(self, row_id):
        entry = self._find_entry(row_id)
        if entry is None:
            return
        # Markierungen entfallen erst, wenn ihr Band erreicht ist - ist Band 14
        # bestellt und kommt jetzt Band 13 dazu, bleibt "bestellt" stehen.
        new_value = self.buffer.increment_baende(row_id)
        if new_value is None:
            QMessageBox.warning(self, "Hinweis", "„Bände (bis)“ enthält keine gültige Zahl.")
            return
        self.selected_row_id = row_id
        self._after_change()
        self._log(f"„{self._find_entry(row_id).get('titel')}“: Bände (bis) auf {new_value} erhöht.")

    def _increment_gelesen(self, row_id):
        entry = self._find_entry(row_id)
        if entry is None:
            return
        result = self.buffer.increment_gelesen(row_id)
        if result is None:
            QMessageBox.warning(self, "Hinweis", "„Gelesen bis“ enthält keine gültige Zahl.")
            return
        if result == logic.EXCEEDS:
            QMessageBox.information(
                self, "Hinweis",
                "„Gelesen bis“ kann nicht über „Bände (bis)“ hinaus erhöht werden – "
                "du kannst nicht mehr Bände gelesen haben, als du besitzt.",
            )
            return
        self.selected_row_id = row_id
        self._after_change()
        self._log(f"„{self._find_entry(row_id).get('titel')}“: Gelesen bis auf {result} erhöht.")

    def import_csv_dialog(self):
        path, _filter = QFileDialog.getOpenFileName(self, "CSV-Datei auswählen", "", "CSV-Dateien (*.csv)")
        if not path:
            return

        try:
            parsed_entries, warnings = import_csv.parse_csv(path)
        except (ValueError, OSError, csv.Error) as exc:
            QMessageBox.critical(self, "CSV-Import", f"Import abgebrochen:\n\n{exc}")
            return

        imported, skipped = self.buffer.import_entries(parsed_entries)
        self._after_change(autosize=bool(imported))
        if imported:
            self._log(f"CSV-Import: {imported} neu importiert, {skipped} übersprungen ({path}).")

        message = (
            f"{imported} neu importiert, {skipped} übersprungen (bereits vorhanden).\n"
            "Die Einträge sind noch nicht gespeichert – bitte auf „💾 Speichern“ klicken."
        )
        if warnings:
            message += "\n\n" + "\n".join(warnings)
        QMessageBox.information(self, "Import", message)

    def import_order_mail_dialog(self):
        """Datei-Auswahl (auch mehrere .eml auf einmal) für Bestellbestätigungen."""
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Bestellbestätigung(en) (E-Mail) auswählen", "", "E-Mail (*.eml)"
        )
        if paths:
            self._import_order_files(paths, "E-Mail-Datei(en)")

    def _import_order_files(self, paths, source):
        """Liest die angegebenen .eml-Dateien (Dialog oder Drag & Drop) ein.
        Die Dateien werden nur gelesen, nichts davon wird abgelegt."""
        items, problems = [], []
        for path in paths:
            try:
                items += order_mail.parse_eml(path)
            except (ValueError, OSError) as exc:
                problems.append(f"{os.path.basename(path)}: {exc}")
        if not items:
            QMessageBox.critical(
                self, "Bestellung einlesen",
                "Aus den gewählten Dateien konnte keine Bestellung gelesen werden:\n\n" + "\n".join(problems),
            )
            return
        self._apply_order_items(items, len(paths) - len(problems), source, problems)

    def _apply_order_items(self, items, mail_count, source, problems=()):
        """Ordnet die Artikel den Einträgen zu und markiert diese: Bestell-
        bestätigung -> Feld "bestellt" (Titel hellblau), Abhol-Benachrichtigung
        -> Feld "angekommen" (roter Balken links am Titel), jeweils mit der
        Bandnummer als Wert (siehe order_mail.FLAG_FIELD). Gemeinsamer Weg
        für .eml-Dateien und den Postfach-Abruf. Ins Log geht nur, welche
        Titel markiert wurden - nichts aus den E-Mails selbst."""
        matches, already_owned, unmatched = order_mail.match_items(items, self.data)
        new_matches = self.buffer.apply_order_matches(matches)  # neu markiert oder auf höheren Band angehoben
        new_ordered = [m for m in new_matches if m.item.kind == order_mail.KIND_ORDER]
        new_arrived = [m for m in new_matches if m.item.kind == order_mail.KIND_PICKUP]

        if new_matches:
            self._after_change()
            for label, group in (("bestellt", new_ordered), ("angekommen", new_arrived)):
                if group:
                    self._log(
                        f"Bestellung eingelesen: {len(group)} Titel als {label} markiert ("
                        + ", ".join(f"{m.entry.get('titel')} Bd. {m.band}" for m in group) + ")."
                    )

        # Eigenes Protokoll je Vorgang (LOG/bestellung_einlesen_*.log), inkl. eigenem
        # Abschnitt für Artikel ohne passenden Eintrag.
        log_path, log_error = None, None
        try:
            log_path = changelog.write_order_log(order_mail.build_log(
                source, mail_count, items, matches, new_matches, already_owned, unmatched, problems,
            ))
        except OSError as exc:
            log_error = str(exc)

        lines = [f"{mail_count} E-Mail(s), {len(items)} Artikel, {len(matches)} Titel zugeordnet."]
        if new_ordered:
            lines.append(f"{len(new_ordered)} neu als bestellt markiert (hellblau).")
        if new_arrived:
            lines.append(f"{len(new_arrived)} neu als angekommen markiert (roter Balken).")
        if new_matches:
            lines.append("Noch nicht gespeichert – bitte auf „💾 Speichern“ klicken.")
        if len(matches) > len(new_matches):
            lines.append(f"{len(matches) - len(new_matches)} waren bereits markiert.")
        if already_owned:
            lines.append(f"{len(already_owned)} Band/Bände waren schon im Bestand.")
        if unmatched:
            lines.append(f"{len(unmatched)} Artikel ohne passenden Eintrag (z. B. Sonderausgaben).")
        if problems:
            lines.append(f"{len(problems)} Datei(en) nicht lesbar.")
        if log_path:
            lines.append(f"Protokoll: {log_path}")
        elif log_error:
            lines.append(f"Protokoll konnte nicht geschrieben werden: {log_error}")

        details = []
        if already_owned:
            details.append("Bereits im Bestand (nicht markiert):")
            details += [f"  {m.entry.get('titel')} – Band {m.band}" for m in already_owned]
            details.append("")
        if unmatched:
            details.append("Keinem Eintrag zugeordnet:")
            details += [f"  {item.name}" for item in unmatched]
            details.append("")
        if problems:
            details.append("Nicht lesbar:")
            details += [f"  {p}" for p in problems]

        box = QMessageBox(QMessageBox.Information, "Bestellung einlesen", "\n".join(lines), QMessageBox.Ok, self)
        if details:
            box.setDetailedText("\n".join(details).strip())
        box.exec()

    # -- Postfach (IMAP)

    def open_mail_settings_dialog(self):
        MailSettingsDialog(self).exec()

    def fetch_orders_from_mailbox(self):
        """Ruft Bestellbestätigungen per IMAP ab (Hintergrund-Thread), lässt
        die gefundenen Mails auswählen und markiert die bestellten Titel."""
        settings = mail_fetch.load_settings()
        if not settings.configured:
            QMessageBox.information(
                self, "Postfach",
                "Der Postfach-Zugang ist noch nicht eingerichtet.\n\n"
                "Bitte unter „Konfigurieren → Postfach (IMAP) …“ Server und Benutzername eintragen.",
            )
            return

        password = (
            self._mail_session_passwords.get(settings.credential_key)
            or mail_fetch.get_saved_password(settings)
        )
        if not password:
            password, ok = QInputDialog.getText(
                self, "Postfach", f"Passwort für {settings.user}\n({settings.host}):", QLineEdit.Password
            )
            if not ok or not password:
                return
        self._mail_session_passwords[settings.credential_key] = password  # nur im Arbeitsspeicher

        progress = QProgressDialog("Rufe Bestellbestätigungen aus dem Postfach ab …", None, 0, 0, self)
        progress.setWindowTitle("Postfach")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        call = AsyncCall(lambda: mail_fetch.fetch_orders(settings, password), self)
        call.finished.connect(lambda mails, error: self._finish_mailbox_fetch(progress, settings, mails, error))
        self._mail_call = call  # Referenz halten, bis das Ergebnis da ist
        call.start()

    def _finish_mailbox_fetch(self, progress, settings, mails, error):
        progress.close()
        self._mail_call = None
        if error is not None:
            self._mail_session_passwords.pop(settings.credential_key, None)  # evtl. falsches Passwort verwerfen
            QMessageBox.critical(self, "Postfach", str(error))
            return
        if not mails:
            QMessageBox.information(
                self, "Postfach",
                f"Keine passenden Mails gefunden (Ordner „{settings.folder}“, letzte {settings.days_back} Tage, "
                f"Absender „{settings.sender or 'egal'}“, Betreff „{settings.subject or 'egal'}“).\n\n"
                "Filter unter „Konfigurieren → Postfach (IMAP) …“ anpassbar.",
            )
            return
        if not any(m.items for m in mails):
            QMessageBox.information(
                self, "Postfach",
                f"{len(mails)} Mail(s) gefunden, aber keine enthält eine auswertbare Artikelliste.",
            )
            return
        dlg = MailSelectDialog(self, mails)
        if not dlg.exec():
            return
        chosen = dlg.selected_mails()
        if not chosen:
            return
        self._apply_order_items([item for m in chosen for item in m.items], len(chosen), "Postfach (IMAP)")

    # -- Drag & Drop von .eml-Dateien auf das Fenster

    @staticmethod
    def _dropped_eml_paths(mime):
        if not mime.hasUrls():
            return []
        paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return [p for p in paths if p.lower().endswith(".eml")]

    def dragEnterEvent(self, event):
        if self._dropped_eml_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self._dropped_eml_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            # Erst nach dem Ablegen verarbeiten: ein Meldungsfenster direkt im
            # dropEvent würde unter Windows die Quelle (Explorer, Thunderbird)
            # blockieren, bis es geschlossen wird.
            QTimer.singleShot(0, lambda: self._import_order_files(paths, "Drag & Drop"))
        else:
            super().dropEvent(event)

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

    def _busy_dialog(self, title, text):
        """Fortschrittsfenster ohne Abbrechen für eine Hintergrund-Aufgabe."""
        progress = QProgressDialog(text, None, 0, 0, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        return progress

    def _import_drive_sync(self):
        try:
            import drive_sync
        except ImportError as exc:
            QMessageBox.critical(
                self, "Google Drive",
                f"Die Google-Bibliotheken fehlen ({exc}).\n\nBitte installieren mit:\npip install -r requirements.txt",
            )
            return None
        return drive_sync

    _DRIVE_HINT = "Falls sich ein Browserfenster zur Google-Anmeldung öffnet, bitte dort anmelden."

    def drive_upload(self):
        if self.dirty:
            answer = QMessageBox.question(
                self, "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Änderungen. Diese müssen zuerst lokal gespeichert werden, "
                "bevor zu Google Drive gesichert werden kann. Jetzt speichern und fortfahren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes or not self.save():
                return
        drive_sync = self._import_drive_sync()
        if drive_sync is None:
            return
        # Im Hintergrund: die erste Anmeldung wartet auf den Browser, das darf
        # die Oberfläche nicht einfrieren ("Keine Rückmeldung").
        progress = self._busy_dialog("Google Drive", f"Sichere zu Google Drive ...\n{self._DRIVE_HINT}")
        call = AsyncCall(drive_sync.upload, self)
        call.finished.connect(lambda _result, error: self._finish_drive_upload(progress, error))
        self._drive_call = call
        call.start()

    def _finish_drive_upload(self, progress, error):
        progress.close()
        self._drive_call = None
        if error is not None:
            QMessageBox.critical(self, "Google Drive", str(error))
            return
        self._log("Zu Google Drive gesichert.")
        QMessageBox.information(self, "Google Drive", "Datenbank wurde erfolgreich zu Google Drive gesichert.")

    def drive_download(self):
        warning = "Die lokale Datenbank wird durch die Version aus Google Drive ersetzt. Fortfahren?"
        if self.dirty:
            warning = "Ungespeicherte Änderungen gehen dabei verloren!\n\n" + warning
        answer = QMessageBox.question(
            self, "Google Drive", warning, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        drive_sync = self._import_drive_sync()
        if drive_sync is None:
            return
        progress = self._busy_dialog("Google Drive", f"Lade von Google Drive ...\n{self._DRIVE_HINT}")
        call = AsyncCall(drive_sync.download, self)
        call.finished.connect(lambda backup_path, error: self._finish_drive_download(progress, backup_path, error))
        self._drive_call = call
        call.start()

    def _finish_drive_download(self, progress, backup_path, error):
        progress.close()
        self._drive_call = None
        if error is not None:
            QMessageBox.critical(self, "Google Drive", str(error))
            return
        try:
            db.init_db()  # ältere Sicherung -> Schema ggf. auf den aktuellen Stand migrieren
            self.buffer.load(db.load_all())
        except Exception as exc:  # noqa: BLE001 - dem Nutzer die Ursache zeigen
            QMessageBox.critical(self, "Google Drive", f"Die geladene Datenbank konnte nicht geöffnet werden:\n\n{exc}")
            return
        self.selected_row_id = None
        self._after_change(autosize=True)
        message = "Datenbank wurde erfolgreich von Google Drive geladen."
        if backup_path:
            message += f"\n\nDie bisherige lokale Datenbank wurde gesichert unter:\n{backup_path}"
        self._log(f"Von Google Drive geladen ({len(self.data)} Einträge, Sicherung: {backup_path or '–'}).")
        QMessageBox.information(self, "Google Drive", message)

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

        try:
            import isbn_lookup
        except ImportError:
            QMessageBox.critical(
                self, "ISBN-Abgleich",
                "Das Paket „requests“ wird dafür benötigt.\n\nBitte installieren mit:\npip install requests",
            )
            return

        progress = QProgressDialog(f"Suche ISBNs für {label} ...", "Abbrechen", 0, 0, self)
        progress.setWindowTitle("ISBN-Abgleich läuft ...")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoReset(False)
        progress.setAutoClose(False)
        # "Abbrechen" soll den Dialog nicht sofort schließen (Standardverhalten),
        # sondern offen lassen, bis der gerade laufende Titel fertig ist.
        cancel_event = threading.Event()
        progress.canceled.disconnect(progress.cancel)
        progress.canceled.connect(lambda: self._cancel_isbn_lookup(progress, cancel_event))
        progress.show()

        # Gesucht wird im aktuellen Zwischenspeicher (auch ungespeicherte
        # Änderungen) - als Kopie, weil der Abgleich im Hintergrund läuft.
        # In die Datenbankdatei schreibt er nur die ISBN-Tabellen.
        entries = copy.deepcopy(self.data)
        db_path = str(db.DB_FILE)

        def run():
            report = isbn_lookup.fill_missing_isbns(
                db_path, only_month=only_month, only_status=only_status, overwrite=overwrite,
                progress=call.progress.emit, cancel=cancel_event, entries=entries,
            )
            if kind == "month":
                bestellliste = isbn_lookup.bestellliste_markdown(db_path, month, year, entries=entries)
            else:
                bestellliste = isbn_lookup.bestellliste_markdown(db_path, status=status, entries=entries)
            return report, bestellliste

        call = AsyncCall(run, self)
        call.progress.connect(lambda done, total, titel: self._update_isbn_progress(
            progress, label, cancel_event, done, total, titel
        ))
        call.finished.connect(lambda result, error: self._finish_isbn_lookup(progress, label, result, error))
        self._isbn_call = call
        call.start()

    @staticmethod
    def _update_isbn_progress(progress, label, cancel_event, done, total, titel):
        if cancel_event.is_set():
            return  # Hinweis "wird abgebrochen" stehen lassen
        progress.setMaximum(total)
        progress.setValue(done)
        progress.setLabelText(f"Suche ISBNs für {label} ...\nTitel {done + 1} von {total}: {titel}")

    @staticmethod
    def _cancel_isbn_lookup(progress, cancel_event):
        cancel_event.set()
        progress.setLabelText(
            "Wird abgebrochen ...\nDer gerade laufende Titel wird noch fertig geprüft; "
            "bereits gefundene ISBNs bleiben gespeichert."
        )
        progress.setCancelButton(None)

    def _finish_isbn_lookup(self, progress, label, result, error):
        progress.close()
        self._isbn_call = None
        # Der Abgleich schreibt nur in die ISBN-Tabellen, nie in `werke` - der
        # Zwischenspeicher bleibt unberührt.
        if error is not None:
            QMessageBox.critical(self, "ISBN-Abgleich", f"Fehler beim Abgleich:\n\n{error}")
            return
        report, bestellliste = result
        if report.abgebrochen:
            label += " – abgebrochen"

        win = IsbnResultWindow(self, label, report, bestellliste)
        win.exec()
