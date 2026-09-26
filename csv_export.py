"""
csv_export.py
Exportiert den aktuellen Bestand (Speicher-Puffer der GUI) als CSV-Datei.
Nutzt bewusst die sprechenden Spaltenbeschriftungen aus database.LABELS als
Kopfzeile, damit der Export auch außerhalb des Programms (z.B. in Excel)
verständlich ist.
"""

import csv

import config
import database as db


def export_csv(path: str, entries, delimiter: str = None) -> int:
    """
    Schreibt `entries` (Liste von Dicts wie im Speicher-Puffer) als
    CSV-Datei nach `path`, in den database.COLUMN_NAMES-Spalten.

    Trennzeichen: config.json "csv_delimiter" (Standard ";" - damit öffnet
    Excel mit deutschen Einstellungen die Datei direkt in Spalten), UTF-8
    mit BOM, damit Umlaute richtig erscheinen. Der CSV-Import erkennt das
    Trennzeichen selbst, ein Export lässt sich also wieder einlesen.

    ISBN, Bestellt-/Angekommen-Markierungen und "Rückstand" sind nicht
    enthalten - sie stehen nicht in database.COLUMN_NAMES.
    Gibt die Anzahl der geschriebenen Zeilen zurück.
    """
    if delimiter is None:
        delimiter = config.get("csv_delimiter", ";")
        if delimiter not in config.ALLOWED_VALUES["csv_delimiter"]:
            delimiter = ";"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow([db.LABELS[c] for c in db.COLUMN_NAMES])
        count = 0
        for entry in entries:
            writer.writerow([entry.get(c, "") or "" for c in db.COLUMN_NAMES])
            count += 1
    return count
