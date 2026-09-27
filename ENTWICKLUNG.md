# Entwicklung

Hinweise für die Arbeit am Quellcode. Installation und Bedienung des
Programms stehen in der [README](README.md).

## Inhalt

1. [Projektstruktur](#1-projektstruktur)
2. [Tests, Linter und CI](#2-tests-linter-und-ci)
3. [exe bauen](#3-exe-bauen)
4. [Neue Version veröffentlichen](#4-neue-version-veröffentlichen)
5. [Datenmodell](#5-datenmodell)

## 1. Projektstruktur

```
├── main.py             Startpunkt: Fehler-Handler, Schutz vor zweitem Start, Hauptfenster
├── gui/                Oberfläche (PySide6/Qt)
│   ├── main_window.py    MangaLibraryApp (Hauptfenster)
│   ├── table.py          MangaTableModel, CellDelegate (Tabelle mit „+1“-Knöpfen)
│   ├── dialogs.py        EntryDialog, ConfigDialog, IsbnLookupDialog, AboutDialog
│   ├── mail_dialogs.py   MailSettingsDialog, MailSelectDialog (Postfach-Abruf)
│   ├── isbn_view.py      IsbnResultWindow (Ergebnis des ISBN-Abgleichs)
│   ├── worker.py         AsyncCall (Hintergrund-Aufgaben mit Qt-Signalen)
│   ├── constants.py      gemeinsame Konstanten und Hilfsfunktionen (kein Qt-Code)
│   └── __init__.py       Re-Export (from gui import MangaLibraryApp)
├── library.py          Zwischenspeicher mit Rückgängig/Wiederholen (ohne Qt, getestet)
├── logic.py            „+1“-Aktionen, Bestell-Markierungen, Formularprüfung
├── database.py         SQLite-Zugriff, Schema-Versionen, Sicherungen (BACKUP/)
├── config.py           config.json: Standardwerte, sicheres Schreiben, Prüfung
├── changelog.py        Änderungsprotokoll, Log-Dateien, Fehler-Log
├── appinfo.py          Versionsnummer und verwendete Module (Hilfe → Über …)
├── models.py           Werk-Dataclass (formales Datenmodell, dict-kompatibel)
├── colors.py           Farbcodierung (VÖ +1, Komplett/Beendet, Verlag, Zebra)
├── sorting.py          Datums- und zahlenbewusste Sortierschlüssel
├── isbn_lookup.py      ISBN-Abgleich (DNB-SRU) und Bestellliste, Sonderausgaben
├── shops.py            Buchhändler-Links für die Bestellliste
├── order_mail.py       Bestell-Mails (.eml) lesen, Artikel den Einträgen zuordnen
├── mail_fetch.py       IMAP-Abruf von Bestellbestätigungen (anbieterunabhängig)
├── drive_sync.py       Google-Drive-Sicherung und -Wiederherstellung
├── import_csv.py       CSV-Import (erkennt Kopfzeile, Trennzeichen, Zeichensatz)
├── csv_export.py       CSV-Export (Semikolon, für Excel)
├── paths.py            Datenordner – neben main.py bzw. neben der exe
├── tests/              automatisierte Tests (pytest)
├── build.bat           baut die exe (eigene Build-Umgebung, feste Versionen)
├── MangaLibrary.spec   PyInstaller-Bauanleitung: was in die exe kommt
├── requirements.txt    Laufzeit-Abhängigkeiten
├── requirements-dev.txt  zusätzlich für die Entwicklung: pytest, Ruff
├── requirements-build.txt  exakte Versionen für den exe-Build
├── pyproject.toml      Konfiguration des Linters Ruff
└── .github/workflows/  automatische Prüfungen auf GitHub (CI)
```

Details zur DNB-Suche (Suchanfrage, Bandfelder, Erkennung von
Sonderausgaben) stehen in den Docstrings von `isbn_lookup.py`.

## 2. Tests, Linter und CI

**Tests:** Für alle Module ohne Qt-Oberfläche gibt es eine pytest-Suite
unter `tests/` – u. a. Zwischenspeicher (Rückgängig/Wiederholen,
Markierungen), „+1“ und Formularprüfung, Datenbank (Migrationen, atomares
Speichern, Sicherungen), ISBN-Abgleich (mit nachgebauten DNB-Antworten),
Bestell-Mails und Postfach-Abruf (mit nachgebautem IMAP-Server),
Konfiguration, CSV sowie Google-Drive-Download (mit nachgebautem Dienst).
Netzwerk wird dabei nicht benötigt.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

**Linter (Ruff):** prüft auf echte Fehler (z. B. ungenutzte Importe,
undefinierte Namen), typische Fallstricke, pauschales `except Exception`
ohne Begründung, Import-Reihenfolge und Zeilenlänge (120 Zeichen). Welche
Regeln gelten, steht in `pyproject.toml`; bewusst ausgenommen sind z. B. die
deutschen Anführungszeichen „…“ in Texten.

```bash
python -m ruff check .          # prüfen
python -m ruff check . --fix    # automatisch Behebbares gleich korrigieren
```

Die Ruff-Version ist in `requirements-dev.txt` fest vorgegeben, damit neue
Regeln einer neueren Version nicht unbemerkt Fehler melden – beim Anheben
einmal `ruff check .` laufen lassen.

**CI:** Bei jedem Push auf `main` und bei jedem Pull Request führt GitHub
Actions (`.github/workflows/tests.yml`) Ruff und die Tests aus – die Tests
auf Windows mit Python 3.9 (älteste unterstützte Version) und 3.14. Das
Ergebnis steht im Pull Request und als Abzeichen oben in der README; im
Reiter „Actions“ lässt sich ein Durchlauf auch von Hand starten.

## 3. exe bauen

Die exe muss auf **Windows** gebaut werden. Dazu `build.bat` per
Doppelklick oder in der Eingabeaufforderung starten; das Ergebnis liegt
danach in `dist\MangaLibrary.exe`.

- **Eigene Umgebung, feste Versionen:** `build.bat` baut in `.venv-build`
  mit den exakt festgelegten Versionen aus `requirements-build.txt` –
  unabhängig davon, was im globalen Python installiert ist. Beim ersten Mal
  wird die Umgebung angelegt (einige Minuten), danach dauert ein Build etwa
  eine halbe Minute. Wie man die Versionen aktualisiert, steht oben in
  `requirements-build.txt`.
- **Eine Bauanleitung:** Was in die exe kommt, steht ausschließlich in
  `MangaLibrary.spec`; `build.bat` ruft nur PyInstaller damit auf.
- **Schlank:** Von Qt kommen nur QtCore/QtGui/QtWidgets hinein (Paket
  `PySide6-Essentials`), von den Google-API-Beschreibungen nur die für
  Google Drive. Die exe ist dadurch etwa 67 MB groß und startet in rund
  1,5 Sekunden.
- `build.bat --no-pause` wartet am Ende nicht auf einen Tastendruck – für
  den Aufruf aus eigenen Skripten.

Meldet die exe ein fehlendes Modul, das Modul in `MangaLibrary.spec` bei
`hiddenimports` ergänzen und neu bauen. Unerwartete Fehler stehen mit allen
Details in `LOG\fehler.log` neben der exe.

## 4. Neue Version veröffentlichen

Die Versionsnummer steht an genau einer Stelle: `VERSION` in `appinfo.py`
(angezeigt unter „Hilfe → Über …“).

1. `VERSION` anheben (z. B. `1.0.3` → `1.0.4`) und per Pull Request mergen.
2. Mit `build.bat` die exe aus dem aktuellen `main` bauen.
3. Auf GitHub ein Release mit dem Tag `v<VERSION>` (z. B. `v1.0.4`) anlegen
   und `dist\MangaLibrary.exe` anhängen.

Neue Bibliotheken bei Bedarf in `appinfo.LIBRARIES` eintragen – dann
erscheinen sie im Über-Dialog, und `MangaLibrary.spec` packt ihre
Versionsangaben automatisch mit in die exe.

## 5. Datenmodell

Die Spalten eines Eintrags sind in `database.COLUMNS` festgelegt, dazu die
unsichtbaren Felder `bestellt` und `angekommen` (`HIDDEN_COLUMNS`, Wert =
Bandnummer der Markierung). Alle Werte werden als Text gespeichert.
Strukturelle Änderungen am Schema laufen über `PRAGMA user_version` und
`database._apply_migrations`.

ISBNs stehen nicht in den Einträgen, sondern in eigenen Tabellen:
`isbn_cache` (normale Ausgabe) und `isbn_sonderausgaben`, jeweils mit dem
Schlüssel Titel + „Bände (bis)“ zum Zeitpunkt der Suche.

`models.Werk` ist eine dataclass mit allen gespeicherten Feldern
(`database.STORED_COLUMN_NAMES`, dynamisch daraus erzeugt). Sie ist
dict-kompatibel (`get`/`[...]`/`update` …) und lässt sich damit anstelle
der einfachen Dicts verwenden, mit denen der Zwischenspeicher (`library.py`)
arbeitet.
