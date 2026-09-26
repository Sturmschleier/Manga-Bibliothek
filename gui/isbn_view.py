"""
gui/isbn_view.py
Ergebnisdarstellung des ISBN-Abgleichs: IsbnWorkerSignals (Qt-Signal für
den Hintergrund-Thread) und IsbnResultWindow (Zusammenfassung + fertige
Bestellliste mit klickbaren Links).
"""

import html
import re

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

import config

class IsbnWorkerSignals(QObject):
    """Eigenes QObject für das Signal, da der eigentliche Abgleich in
    einem Hintergrund-Thread läuft (threading.Thread) - Qt liefert
    Signal-Emissionen aus einem anderen Thread automatisch sicher
    ("queued") an den Haupt-Thread aus."""
    finished = Signal(object, object, object)  # report, bestellliste, error


class IsbnResultWindow(QDialog):
    """Separates Ausgabefenster: Zusammenfassung des ISBN-Abgleichs und die
    fertige Bestellliste, mit echten klickbaren Links (QTextBrowser rendert
    HTML nativ inkl. anklickbarer Hyperlinks) und farblich hervorgehobenen
    Fallback-Zeilen (keine ISBN automatisch gefunden)."""

    # Nicht-gierig bis zur schließenden Klammer, die tatsächlich von
    # Whitespace/Zeilenende/Tabellen-Pipe gefolgt wird (statt bei der
    # ERSTEN Klammer abzubrechen) - sonst würden URLs, die selbst runde
    # Klammern enthalten (z.B. die buchhandel.de-Suchlinks), mitten in
    # der URL abgeschnitten und der Rest als sichtbarer Rohtext übrig
    # bleiben.
    _LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://\S+?)\)(?=\s|$|\|)|(https?://\S+)")
    _FALLBACK_BG = "#FBD3D3"

    def __init__(self, parent, label, report, bestellliste_md):
        super().__init__(parent)
        self.setWindowTitle(f"ISBN-Abgleich & Bestellliste – {label}")
        self.resize(860, 620)
        # QDialog hat standardmäßig nur einen Schließen-Button - für die lange
        # Bestellliste sind Maximieren/Minimieren und ein Größenziehpunkt
        # aber sinnvoll. CustomizeWindowHint ist nötig, damit Windows die
        # explizit gewählten Titelleisten-Buttons auch wirklich anzeigt.
        self.setWindowFlags(
            Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self.bestellliste_md = bestellliste_md or ""
        # Welche Fallback-Domain markiert eine "nicht gefunden"-Zeile, hängt
        # vom konfigurierten Anbieter ab (buchhandel.de oder manga-passion) -
        # nicht mehr fest verdrahtet, sonst würde die Hervorhebung greifen,
        # sobald der Standard-Anbieter geändert wird.
        provider = config.get("isbn_fallback_provider", "buchhandel.de")
        self._fallback_marker = "manga-passion.de" if provider == "manga-passion" else "buchhandel.de"

        # Fenster bewusst fest auf ein helles Thema setzen, unabhängig vom
        # Systemthema (z.B. Windows-Dunkelmodus): sonst kann der dunkle
        # Text auf einem dann ebenfalls dunklen Standard-Hintergrund kaum
        # noch lesbar sein - das war genau das Problem mit den zuvor nur
        # für die Fallback-Zeilen fest vorgegebenen Farben.
        self.setStyleSheet(
            "QDialog { background-color: #ffffff; }"
            "QLabel { color: #1a1a1a; }"
            "QTextBrowser { background-color: #ffffff; color: #1a1a1a; border: 1px solid #cccccc; }"
            "QPushButton { background-color: #f0f0f0; color: #1a1a1a; border: 1px solid #999999;"
            " padding: 5px 12px; }"
            "QPushButton:hover { background-color: #e2e2e2; }"
            "QPushButton:pressed { background-color: #d0d0d0; }"
        )

        layout = QVBoxLayout(self)

        legend = QHBoxLayout()
        swatch = QLabel()
        swatch.setFixedSize(14, 14)
        swatch.setStyleSheet(f"background-color: {self._FALLBACK_BG}; border: 1px solid #888;")
        legend.addWidget(swatch)
        legend.addWidget(QLabel("= keine ISBN automatisch gefunden (manueller Fallback-Link)"))
        legend.addStretch(1)
        layout.addLayout(legend)

        content = report.summary() if report else "(kein Ergebnis)"
        content += "\n\n" + ("─" * 70) + "\n\nBestellliste:\n\n" + self.bestellliste_md

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setFont(self._monospace_font())
        self.browser.setHtml(self._to_html(content))
        layout.addWidget(self.browser, 1)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Bestellliste in Zwischenablage kopieren")
        self.copy_btn.clicked.connect(self._copy)
        self.maximize_btn = QPushButton("Maximieren")
        self.maximize_btn.clicked.connect(self._toggle_maximized)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.copy_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.maximize_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "maximize_btn"):
            self.maximize_btn.setText("Wiederherstellen" if self.isMaximized() else "Maximieren")

    @staticmethod
    def _monospace_font():
        from PySide6.QtGui import QFont
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        return font

    def _to_html(self, content):
        """Wandelt den einfachen Text (mit Markdown-Links/nackten URLs) in
        HTML um: echte <a>-Links, Zeilen mit dem Fallback-Link des
        konfigurierten Anbieters (buchhandel.de oder manga-passion, siehe
        self._fallback_marker) werden zusätzlich farblich hervorgehoben.

        Text- und Linkfarbe werden hier bewusst fest vorgegeben (statt die
        Systemfarbe zu übernehmen) - sonst kann z.B. bei einem hellen
        Systemtext auf dem rosa Fallback-Hintergrund kaum lesbarer Kontrast
        entstehen."""
        TEXT_COLOR = "#1a1a1a"
        LINK_COLOR = "#0b57d0"

        out_lines = []
        for line in content.split("\n"):
            is_fallback = self._fallback_marker in line

            pos = 0
            pieces = []
            for m in self._LINK_RE.finditer(line):
                start, end = m.span()
                if start > pos:
                    pieces.append(html.escape(line[pos:start]))
                if m.group(1) is not None:
                    label, url = m.group(1), m.group(2)
                else:
                    label = url = m.group(3)
                pieces.append(
                    f'<a href="{html.escape(url)}" style="color:{LINK_COLOR};">{html.escape(label)}</a>'
                )
                pos = end
            if pos < len(line):
                pieces.append(html.escape(line[pos:]))

            line_html = "".join(pieces) if pieces else "&nbsp;"
            style = f"white-space: pre-wrap; margin: 0; color:{TEXT_COLOR};"
            if is_fallback:
                style += f" background-color:{self._FALLBACK_BG};"
            out_lines.append(f'<div style="{style}">{line_html}</div>')

        return "".join(out_lines)

    def _copy(self):
        from PySide6.QtCore import QTimer
        QApplication.clipboard().setText(self.bestellliste_md)

        # Sichtbare, kurze Rückmeldung, dass das Kopieren tatsächlich
        # funktioniert hat (vorher passierte das ohne jede Reaktion).
        original_text = self.copy_btn.text()
        self.copy_btn.setText("✓ In Zwischenablage kopiert!")
        self.copy_btn.setEnabled(False)
        QTimer.singleShot(1500, lambda: (self.copy_btn.setText(original_text), self.copy_btn.setEnabled(True)))
