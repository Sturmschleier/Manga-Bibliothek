"""
gui/mail_dialogs.py
Dialoge für den Postfach-Abruf von Bestellbestätigungen (siehe
mail_fetch.py): MailSettingsDialog (IMAP-Zugang, anbieterunabhängig) und
MailSelectDialog (gefundene Bestellmails auswählen).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

import mail_fetch
import order_mail

from .worker import AsyncCall

_SECURITY_LABELS = {"ssl": "SSL/TLS (Port 993)", "starttls": "STARTTLS (Port 143)"}


class MailSettingsDialog(QDialog):
    """IMAP-Zugang und Suchfilter für den Postfach-Abruf. Das Passwort wird
    nie in config.json geschrieben: wahlweise in die Windows-Anmelde-
    informationen (falls verfügbar), sonst wird es bei jedem Abruf erfragt."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Postfach (IMAP) – Einstellungen")
        self._settings = mail_fetch.load_settings()
        self._test_call = None

        form = QFormLayout()

        self.preset_box = QComboBox()
        self.preset_box.addItem("Eigener Server / manuell")
        self.preset_box.addItems(mail_fetch.PRESETS)
        self.preset_box.currentIndexChanged.connect(self._apply_preset)
        form.addRow("Anbieter (Vorlage):", self.preset_box)

        self.host_input = QLineEdit(self._settings.host)
        self.host_input.setPlaceholderText("z. B. imap.gmx.net")
        form.addRow("IMAP-Server:", self.host_input)

        port_row = QHBoxLayout()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(self._settings.port)
        port_row.addWidget(self.port_input)
        self.security_box = QComboBox()
        for key, label in _SECURITY_LABELS.items():
            self.security_box.addItem(label, key)
        self.security_box.setCurrentIndex(max(0, self.security_box.findData(self._settings.security)))
        self.security_box.currentIndexChanged.connect(self._sync_port_to_security)
        port_row.addWidget(self.security_box, 1)
        form.addRow("Port / Verschlüsselung:", port_row)

        self.user_input = QLineEdit(self._settings.user)
        self.user_input.setPlaceholderText("meist die E-Mail-Adresse")
        form.addRow("Benutzername:", self.user_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        has_saved = mail_fetch.get_saved_password(self._settings) is not None
        self.password_input.setPlaceholderText("gespeichert – leer lassen zum Beibehalten" if has_saved else "")
        form.addRow("Passwort:", self.password_input)

        self.save_pw_box = QCheckBox("Passwort in den Windows-Anmeldeinformationen speichern")
        self.save_pw_box.setChecked(has_saved)
        if not mail_fetch.keyring_available():
            self.save_pw_box.setEnabled(False)
            self.save_pw_box.setToolTip(
                "Nicht verfügbar (Paket „keyring“ fehlt) – das Passwort wird dann bei jedem Abruf erfragt."
            )
        form.addRow("", self.save_pw_box)

        hint = QLabel(
            "Das Passwort steht nie in der config.json. Bei GMX, WEB.DE, Gmail u. ä. ist oft ein "
            "App-Passwort bzw. die Freigabe des IMAP-Zugriffs in den Kontoeinstellungen nötig."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        form.addRow("", hint)

        self.folder_input = QLineEdit(self._settings.folder)
        form.addRow("Ordner:", self.folder_input)
        self.sender_input = QLineEdit(self._settings.sender)
        self.sender_input.setPlaceholderText("leer = alle Absender")
        form.addRow("Absender enthält:", self.sender_input)
        self.subject_input = QLineEdit(self._settings.subject)
        self.subject_input.setPlaceholderText("leer = jeder Betreff")
        form.addRow("Betreff enthält:", self.subject_input)

        self.days_input = QSpinBox()
        self.days_input.setRange(1, 3650)
        self.days_input.setSuffix(" Tage")
        self.days_input.setValue(self._settings.days_back)
        form.addRow("Zeitraum (zurück):", self.days_input)
        self.max_input = QSpinBox()
        self.max_input.setRange(1, 500)
        self.max_input.setValue(self._settings.max_messages)
        form.addRow("Max. Mails je Abruf:", self.max_input)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        btn_row = QHBoxLayout()
        self.test_btn = QPushButton("Verbindung testen")
        self.test_btn.clicked.connect(self._test_connection)
        clear_btn = QPushButton("Gespeichertes Passwort löschen")
        clear_btn.clicked.connect(self._delete_password)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.test_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addLayout(btn_row)
        self.setMinimumWidth(520)

    # ------------------------------------------------------------ Hilfen

    def _apply_preset(self, index):
        if index <= 0:
            return
        host, port, security = mail_fetch.PRESETS[self.preset_box.currentText()]
        self.host_input.setText(host)
        self.security_box.setCurrentIndex(self.security_box.findData(security))
        self.port_input.setValue(port)

    def _sync_port_to_security(self):
        # Nur die beiden Standard-Ports automatisch mitziehen, eigene Ports nicht überschreiben.
        if self.port_input.value() in (993, 143):
            self.port_input.setValue(993 if self.security_box.currentData() == "ssl" else 143)

    def _current_settings(self) -> mail_fetch.MailSettings:
        return mail_fetch.MailSettings(
            host=self.host_input.text().strip(),
            port=self.port_input.value(),
            security=self.security_box.currentData(),
            user=self.user_input.text().strip(),
            folder=self.folder_input.text().strip() or "INBOX",
            sender=self.sender_input.text().strip(),
            subject=self.subject_input.text().strip(),
            days_back=self.days_input.value(),
            max_messages=self.max_input.value(),
        )

    def _password_for(self, settings):
        return self.password_input.text() or mail_fetch.get_saved_password(settings) or ""

    # ------------------------------------------------------------ Aktionen

    def _test_connection(self):
        settings = self._current_settings()
        password = self._password_for(settings)
        if not password:
            self.status_label.setText("Bitte zum Testen ein Passwort eintragen.")
            return
        self.test_btn.setEnabled(False)
        self.status_label.setText("Teste Verbindung …")
        self._test_call = AsyncCall(lambda: mail_fetch.test_connection(settings, password), self)
        self._test_call.finished.connect(self._on_test_done)
        self._test_call.start()

    def _on_test_done(self, count, error):
        self.test_btn.setEnabled(True)
        if error is not None:
            self.status_label.setText(f"❌ {error}")
        else:
            self.status_label.setText(f"✔ Verbindung und Anmeldung erfolgreich ({count} Nachrichten im Ordner).")

    def _delete_password(self):
        mail_fetch.delete_saved_password(self._current_settings())
        self.save_pw_box.setChecked(False)
        self.password_input.setPlaceholderText("")
        self.status_label.setText("Gespeichertes Passwort gelöscht.")

    def _save(self):
        settings = self._current_settings()
        old = self._settings
        mail_fetch.save_settings(settings)
        if old.credential_key != settings.credential_key and old.user:
            mail_fetch.delete_saved_password(old)  # Zugang wurde geändert -> altes Passwort nicht verwaisen lassen

        password = self.password_input.text()
        if self.save_pw_box.isChecked():
            if password and not mail_fetch.save_password(settings, password):
                QMessageBox.warning(
                    self, "Passwort", "Das Passwort konnte nicht gespeichert werden - es wird beim Abruf erfragt."
                )
        else:
            mail_fetch.delete_saved_password(settings)
        self.accept()


class MailSelectDialog(QDialog):
    """Zeigt die im Postfach gefundenen Bestellmails zur Auswahl. Nur Mails
    mit auswertbarer Artikelliste sind wählbar (alle vorausgewählt)."""

    def __init__(self, parent, mails):
        super().__init__(parent)
        self.setWindowTitle("Bestellungen aus dem Postfach")
        self._usable = [m for m in mails if m.items]
        skipped = len(mails) - len(self._usable)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Diese Bestellbestätigungen wurden gefunden – welche einlesen?"))

        self.list_widget = QListWidget()
        for mail in self._usable:
            when = mail.date.strftime("%d.%m.%Y") if mail.date else "ohne Datum"
            count = sum(i.menge for i in mail.items)
            arrived = all(i.kind == order_mail.KIND_PICKUP for i in mail.items)
            kind = "abholbereit" if arrived else "Bestellung"
            item = QListWidgetItem(f"{when}  ·  {kind}  ·  {mail.subject or '(ohne Betreff)'}  ·  {count} Artikel")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, 1)

        if skipped:
            note = QLabel(
                f"{skipped} weitere Mail(s) ohne auswertbare Artikelliste (z. B. Versandmitteilungen "
                "oder nicht lesbare Mails) wurden übersprungen."
            )
            note.setStyleSheet("color: #666;")
            note.setWordWrap(True)
            layout.addWidget(note)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Einlesen")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        self.setMinimumWidth(560)

    def selected_mails(self):
        return [
            mail for row, mail in enumerate(self._usable)
            if self.list_widget.item(row).checkState() == Qt.Checked
        ]
