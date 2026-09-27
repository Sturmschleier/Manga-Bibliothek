"""
appinfo.py
Version und Programminformationen für den Dialog "Hilfe → Über …" - ohne
Qt, damit sie sich testen lassen.

Neue Version veröffentlichen: VERSION anheben, mergen und das GitHub-Release
mit dem Tag "v<VERSION>" anlegen (siehe README, Abschnitt "Neue Version").
"""

import platform
import sqlite3
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Optional

VERSION = "1.0.3"
REPOSITORY_URL = "https://github.com/Sturmschleier/Manga-Bibliothek"

# Verwendete Bibliotheken: (Anzeigename, Paketnamen für die Versionsabfrage,
# wofür das Programm sie braucht, Lizenz). Die Paketnamen nutzt auch
# MangaLibrary.spec, um die Versionsangaben mit in die exe zu packen.
LIBRARIES = (
    ("PySide6 (Qt für Python)", ("PySide6_Essentials", "PySide6"), "Programmoberfläche", "LGPL-3.0"),
    ("requests", ("requests",), "ISBN-Abgleich (Abfragen bei der DNB)", "Apache-2.0"),
    ("google-api-python-client", ("google-api-python-client",), "Sicherung in Google Drive", "Apache-2.0"),
    ("google-auth", ("google-auth",), "Anmeldung bei Google", "Apache-2.0"),
    ("google-auth-oauthlib", ("google-auth-oauthlib",), "Google-Anmeldung im Browser", "Apache-2.0"),
    ("google-auth-httplib2", ("google-auth-httplib2",), "Verbindung zu Google", "Apache-2.0"),
    ("keyring", ("keyring",), "Postfach-Passwort in den Windows-Anmeldeinformationen", "MIT"),
)


@dataclass
class Component:
    name: str
    version: Optional[str]   # None = nicht installiert (die Funktion steht dann nicht zur Verfügung)
    zweck: str
    lizenz: str


def _package_version(names) -> Optional[str]:
    """Version des ersten installierten Pakets aus `names` (ohne es zu
    importieren), sonst None."""
    for name in names:
        for candidate in (name, name.replace("_", "-"), name.replace("-", "_")):
            try:
                return metadata.version(candidate)
            except metadata.PackageNotFoundError:
                continue
    return None


def components(qt_version: Optional[str] = None) -> list[Component]:
    """Laufzeit und verwendete Bibliotheken mit ihren Versionen. `qt_version`
    liefert die Oberfläche (QtCore.qVersion()), da dieses Modul ohne Qt
    auskommen soll."""
    result = [
        Component("Python", f"{platform.python_version()} ({platform.architecture()[0]})",
                  "Programmiersprache und Laufzeit", "PSF-2.0"),
    ]
    if qt_version:
        result.append(Component("Qt", qt_version, "Grafik-Bibliothek der Oberfläche", "LGPL-3.0"))
    result.append(Component("SQLite", sqlite3.sqlite_version, "Datenbank der Sammlung", "Public Domain"))
    for name, packages, zweck, lizenz in LIBRARIES:
        result.append(Component(name, _package_version(packages), zweck, lizenz))
    return result


def about_text(qt_version: Optional[str] = None, data_dir: Optional[str] = None) -> str:
    """Programminformationen als Text - z.B. zum Kopieren für eine Fehlermeldung."""
    frozen = " (exe)" if getattr(sys, "frozen", False) else ""
    lines = [f"Manga & Light Novel Bibliothek {VERSION}{frozen}", REPOSITORY_URL]
    if data_dir:
        lines.append(f"Datenordner: {data_dir}")
    lines.append(f"Betriebssystem: {platform.platform()}")
    lines.append("")
    lines.append("Verwendete Module:")
    for c in components(qt_version):
        lines.append(f"  {c.name}: {c.version or 'nicht installiert'} – {c.zweck} ({c.lizenz})")
    return "\n".join(lines)
