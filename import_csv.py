"""
import_csv.py
Liest eine CSV-Datei (Format wie "Manga - Besitz.csv") ein und gibt eine
Liste von Einträgen (Dicts) zurück.

Die Kopfzeile wird geprüft und - soweit möglich - namensbasiert den
internen Spalten zugeordnet (nicht rein positionsbasiert). Das erkennt
sowohl die exakten Spaltenbeschriftungen aus database.LABELS (z.B. beim
Re-Import einer zuvor exportierten CSV) als auch die etwas abweichenden
Beschriftungen der ursprünglichen Liste (z.B. "bis" statt "Bände (bis)").
Passt die Spaltenanzahl nicht oder lässt sich die Kopfzeile gar nicht
zuordnen, wird das klar gemeldet statt stillschweigend falsche/verschobene
Daten zu erzeugen.

Schreibt bewusst NICHT in die Datenbank – das Einfügen in den
Speicher-Puffer und das spätere aktive Speichern übernimmt die GUI
(gui.py), damit importierte Daten wie jede andere Änderung erst durch
einen expliziten Speichern-Klick dauerhaft werden.

Als eigenständiges Skript aufrufbar für einen direkten Import ohne GUI:
    python import_csv.py "Manga - Besitz.csv"
Dabei wird sofort in die Datenbank geschrieben (kein Puffer, da keine GUI-
Sitzung existiert).
"""

import csv
import sys
from pathlib import Path

import database as db

# Reihenfolge wie im übrigen Programm - aus database.COLUMN_NAMES
# abgeleitet, damit hier keine zweite, unabhängig zu pflegende Spalten-
# liste entstehen kann, die mit der Zeit auseinanderdriftet.
CSV_FIELDS = list(db.COLUMN_NAMES)

# Bekannte, akzeptierte Kopfzeilen-Bezeichnungen je interner Spalte
# (klein geschrieben, ohne führende/nachgestellte Leerzeichen für den
# Vergleich). Deckt sowohl database.LABELS als auch die etwas informelleren
# Original-Beschriftungen der ursprünglichen Liste ab.
_HEADER_ALIASES = {col: {db.LABELS[col].strip().lower()} for col in db.COLUMN_NAMES}
_HEADER_ALIASES["titel"] |= {"", "titel"}
_HEADER_ALIASES["baende_bis"] |= {"bis", "bände", "baende (bis)", "baende"}

# "Rückstand" ist eine reine Anzeige-/Berechnungsspalte (siehe gui.py) -
# nie Teil des gespeicherten Datenmodells. Taucht sie trotzdem in einer zu
# importierenden CSV-Datei auf (z.B. weil ein eigener Export wieder
# importiert wird), wird sie komplett ignoriert statt den Import wegen
# einer "falschen" Spaltenanzahl abzubrechen.
_IGNORED_HEADER_ALIASES = {"rückstand", "ruckstand"}


def _match_columns(header_row):
    """
    Versucht, jede Spalte der Kopfzeile eindeutig einer internen Spalte
    zuzuordnen (unabhängig von der Reihenfolge in der Datei). Gibt eine
    Liste interner Spalten-Schlüssel in der Reihenfolge der Datei zurück,
    oder None, wenn nicht ALLE Spalten eindeutig erkannt werden konnten.
    """
    mapping = []
    used = set()
    for raw in header_row:
        name = (raw or "").strip().lower()
        found = None
        for col, aliases in _HEADER_ALIASES.items():
            if name in aliases and col not in used:
                found = col
                break
        if found is None:
            return None
        mapping.append(found)
        used.add(found)
    if used != set(CSV_FIELDS):
        return None
    return mapping


def parse_csv(path: str):
    """
    Liest die CSV-Datei ein und gibt (entries, warnings) zurück:
      - entries: Liste von Dicts (ohne 'id' - das vergibt erst die
        Datenbank beim Speichern)
      - warnings: Liste von Hinweistexten, z.B. wenn die Spalten anhand
        einer abweichenden Kopfzeile automatisch zugeordnet wurden

    Löst ValueError aus, wenn die Datei leer ist oder die Spaltenanzahl
    nicht zur erwarteten Spaltenzahl passt (statt stillschweigend
    Daten in falsche Felder zu schreiben).
    """
    warnings = []
    expected_count = len(CSV_FIELDS)

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError("Die CSV-Datei ist leer.")
        raw_rows = list(reader)

        # Eine vorhandene "Rückstand"-Spalte komplett aus Kopfzeile UND allen
        # Datenzeilen entfernen, bevor die reguläre Validierung/Zuordnung
        # beginnt - unabhängig davon, an welcher Position sie steht.
        ignored_indexes = [
            i for i, raw in enumerate(header)
            if (raw or "").strip().lower() in _IGNORED_HEADER_ALIASES
        ]
        if ignored_indexes:
            header = [v for i, v in enumerate(header) if i not in ignored_indexes]
            raw_rows = [[v for i, v in enumerate(row) if i not in ignored_indexes] for row in raw_rows]
            warnings.append(
                "Die Spalte „Rückstand“ wurde in der Datei gefunden und beim Import "
                "ignoriert (sie wird nur live berechnet, nie gespeichert)."
            )

        if len(header) != expected_count:
            raise ValueError(
                f"Die CSV-Datei hat {len(header)} Spalten, erwartet werden {expected_count}. "
                "Bitte Format bzw. Kopfzeile der Datei prüfen."
            )

        mapping = _match_columns(header)
        if mapping is None:
            mapping = list(CSV_FIELDS)
            warnings.append(
                "Die Kopfzeile konnte nicht eindeutig erkannt werden - Spalten wurden "
                "anhand der Standard-Reihenfolge zugeordnet (Titel, Bände (bis), "
                "Komplett, Beendet, Gelesen bis, Typ, Zugang, Verlag, Kommentar, "
                "VÖ +1 … VÖ +5). Bitte das Ergebnis nach dem Import kurz prüfen."
            )
        elif mapping != CSV_FIELDS:
            warnings.append(
                "Die Spalten der CSV-Datei standen in abweichender Reihenfolge und "
                "wurden anhand der Kopfzeile automatisch richtig zugeordnet."
            )

        titel_index = mapping.index("titel")
        entries = []
        for row in raw_rows:
            if not row or len(row) <= titel_index or not row[titel_index].strip():
                continue
            row = (row + [""] * expected_count)[:expected_count]
            entries.append(dict(zip(mapping, [v.strip() for v in row])))

    return entries, warnings


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Verwendung: python import_csv.py <pfad_zur_csv_datei>")
        sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"Datei nicht gefunden: {csv_path}")
        sys.exit(1)

    db.init_db()
    bestand = db.load_all()
    existing_titles = {e["titel"].strip().lower() for e in bestand if e.get("titel")}

    try:
        parsed_entries, warnings = parse_csv(str(csv_path))
    except ValueError as exc:
        print(f"Import abgebrochen: {exc}")
        sys.exit(1)

    for warning in warnings:
        print(f"Hinweis: {warning}")

    imported, skipped = 0, 0
    for entry in parsed_entries:
        if entry["titel"].strip().lower() in existing_titles:
            skipped += 1
            continue
        bestand.append(entry)
        existing_titles.add(entry["titel"].strip().lower())
        imported += 1

    db.replace_all(bestand)
    print(f"Import abgeschlossen: {imported} neu importiert, {skipped} übersprungen (bereits vorhanden).")
