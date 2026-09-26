"""
gui/dialogs.py
Kleinere, in sich geschlossene Dialoge: EntryDialog (Werk anlegen/
bearbeiten), ConfigDialog (config.json direkt editieren), IsbnLookupDialog
(Auswahl vor einem ISBN-Abgleich).
"""

import json
from datetime import date

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QSpinBox, QVBoxLayout,
)

import config
import database as db
import logic
import shops

from .constants import JA_NEIN_OPTIONEN, TYP_OPTIONEN

class EntryDialog(QDialog):
    """Formular zum Anlegen/Bearbeiten eines einzelnen Werks (alle Spalten).
    Schreibt nicht selbst in den Puffer, sondern übergibt die Werte an
    `on_save` - Puffer-Verwaltung bleibt Aufgabe der Hauptklasse.
    Vor dem Übernehmen werden die Eingaben geprüft (logic.validate_entry);
    `other_titles` sind die Titel aller anderen Einträge (klein geschrieben)
    für die Prüfung auf doppelte Titel."""

    def __init__(self, parent, title, on_save, initial=None, verlag_values=None, other_titles=()):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.on_save = on_save
        self.other_titles = other_titles

        form = QFormLayout()
        self.fields = {}

        for col in db.COLUMN_NAMES:
            initial_value = (initial.get(col) if initial else "") or ""

            if col == "typ":
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(TYP_OPTIONEN)
                widget.setCurrentText(initial_value)
            elif col in ("komplett", "beendet"):
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(JA_NEIN_OPTIONEN)
                widget.setCurrentText(initial_value)
            elif col == "verlag":
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(verlag_values or [])
                widget.setCurrentText(initial_value)
            else:
                widget = QLineEdit(initial_value)

            widget.setMinimumWidth(280)
            form.addRow(db.LABELS[col], widget)
            self.fields[col] = widget

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Übernehmen")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btn_row)

    def _field_value(self, col):
        widget = self.fields[col]
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return widget.text().strip()

    def _save(self):
        values = {col: self._field_value(col) for col in db.COLUMN_NAMES}
        problems = logic.validate_entry(values, self.other_titles)
        if problems:
            QMessageBox.warning(self, "Bitte prüfen", "\n".join(problems))
            return
        self.on_save(values)
        self.accept()


# ---------------------------------------------------------------------------
# Zentrale Konfiguration
# ---------------------------------------------------------------------------

class ConfigDialog(QDialog):
    """Direkter Editor für die zentrale Konfigurationsdatei (config.json):
    zeigt den rohen, formatierten JSON-Inhalt in einem Textfeld, prüft beim
    Speichern JSON-Syntax sowie Typen und Werte der bekannten Einstellungen
    (config.validate) und schreibt erst dann über config.save() zurück."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Konfiguration bearbeiten")
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Datei: {config.CONFIG_FILE}"))

        info = QLabel(
            "z.B. „isbn_shop_name“/„isbn_shop_url_template“ (Standard-Buchhändler für\n"
            "gefundene ISBNs, {isbn} wird durch die jeweilige ISBN ersetzt), "
            "„isbn_fallback_provider“\n(\"buchhandel.de\" oder \"manga-passion\"), "
            "„follow_selection_after_edit“, „sidebar_width_fraction“."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(json.dumps(config.load(), indent=2, ensure_ascii=False, sort_keys=True))
        font = self.editor.font()
        font.setFamily("Consolas")
        self.editor.setFont(font)
        layout.addWidget(self.editor, 1)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _save(self):
        text = self.editor.toPlainText()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            self.error_label.setText(f"Ungültiges JSON: {exc}")
            return
        if not isinstance(parsed, dict):
            self.error_label.setText("Der Inhalt muss ein JSON-Objekt sein (z.B. { \"schlüssel\": \"wert\" }).")
            return
        problems = config.validate(parsed)
        if problems:
            self.error_label.setText("Nicht gespeichert:\n" + "\n".join(problems))
            return
        config.save(parsed)
        self.accept()


class IsbnLookupDialog(QDialog):
    """Eingabefenster für den ISBN-Abgleich / die Bestellliste. Bietet drei
    Auswahlarten: Monat/Jahr (VÖ +1 in diesem Zeitraum), oder alle Titel
    mit VÖ +1 exakt "TBA" bzw. exakt "NA"."""

    def __init__(self, parent, on_submit):
        super().__init__(parent)
        self.setWindowTitle("ISBN-Abgleich / Bestellliste")
        self.on_submit = on_submit
        today = date.today()

        layout = QVBoxLayout(self)

        info = QLabel(
            "Sucht für die ausgewählten Titel die ISBN des nächsten\n"
            "Bandes bei der DNB (eingeschränkt auf das aktuelle\n"
            "Kalenderjahr und das Folgejahr) und erstellt eine\n"
            "Bestellliste mit Links in einem eigenen Fenster."
        )
        layout.addWidget(info)

        shop_row = QHBoxLayout()
        shop_row.addWidget(QLabel("Bestellen bei:"))
        self.shop_box = QComboBox()
        self.shop_box.addItems(list(shops.available()))
        self.shop_box.setCurrentText(shops.active_name())
        self.shop_box.setToolTip("Buchhändler, zu dem die gefundenen ISBNs in der Bestellliste verlinkt werden")
        shop_row.addWidget(self.shop_box)
        shop_row.addSpacing(16)
        shop_row.addWidget(QLabel("Fallback-Suche:"))
        fallback_lbl = QLabel(f"<b>{config.get('isbn_fallback_provider', 'buchhandel.de')}</b>")
        shop_row.addWidget(fallback_lbl)
        shop_row.addStretch(1)
        shop_hint = QLabel("(änderbar über „Konfigurieren → Konfiguration …“)")
        shop_hint.setStyleSheet("color: #666;")
        shop_row.addWidget(shop_hint)
        layout.addLayout(shop_row)

        self.month_radio = QRadioButton("Nach Monat/Jahr (VÖ +1):")
        self.month_radio.setChecked(True)
        self.month_radio.toggled.connect(self._update_state)
        layout.addWidget(self.month_radio)

        month_row = QHBoxLayout()
        month_row.addSpacing(24)
        month_row.addWidget(QLabel("Monat (1–12):"))
        self.month_input = QSpinBox()
        self.month_input.setRange(1, 12)
        self.month_input.setValue(today.month)
        month_row.addWidget(self.month_input)
        month_row.addSpacing(12)
        month_row.addWidget(QLabel("Jahr:"))
        self.year_input = QSpinBox()
        self.year_input.setRange(1900, 2100)
        self.year_input.setValue(today.year)
        month_row.addWidget(self.year_input)
        month_row.addStretch(1)
        layout.addLayout(month_row)

        self.tba_radio = QRadioButton('Alle Titel mit VÖ +1 = "TBA"')
        layout.addWidget(self.tba_radio)

        self.na_radio = QRadioButton('Alle Titel mit VÖ +1 = "NA"')
        layout.addWidget(self.na_radio)

        self.overwrite_checkbox = QCheckBox("Vorhandene ISBNs erneut prüfen (überschreiben)")
        self.overwrite_checkbox.setToolTip(
            "Titel, für die es bereits einen ISBN-Cache-Eintrag für den aktuellen Band-Stand "
            "gibt, werden normalerweise übersprungen, um die DNB nicht unnötig erneut "
            "abzufragen. Aktivieren, um sie trotzdem neu zu suchen - "
            "z. B. wenn sich die Zuordnungslogik geändert hat oder ein Treffer falsch war."
        )
        layout.addWidget(self.overwrite_checkbox)

        btn_row = QHBoxLayout()
        start_btn = QPushButton("Suche starten")
        start_btn.clicked.connect(self._submit)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(start_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _update_state(self):
        enabled = self.month_radio.isChecked()
        self.month_input.setEnabled(enabled)
        self.year_input.setEnabled(enabled)

    def _submit(self):
        shops.set_active(self.shop_box.currentText())  # Auswahl dauerhaft merken (auch für die Bestellliste)
        overwrite = self.overwrite_checkbox.isChecked()
        if self.month_radio.isChecked():
            self.on_submit(("month", self.month_input.value(), self.year_input.value(), overwrite))
        elif self.tba_radio.isChecked():
            self.on_submit(("status", "TBA", overwrite))
        else:
            self.on_submit(("status", "NA", overwrite))
        self.accept()
