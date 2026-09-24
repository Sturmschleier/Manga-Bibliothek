"""
csv_export.py
Exportiert den aktuellen Bestand (Speicher-Puffer der GUI) als CSV-Datei.
Nutzt bewusst die sprechenden Spaltenbeschriftungen aus database.LABELS als
Kopfzeile, damit der Export auch außerhalb des Programms (z.B. in Excel)
verständlich ist.
"""

import csv

import database as db


def export_csv(path: str, entries) -> int:
    """
    Schreibt `entries` (Liste von Dicts wie im Speicher-Puffer) als
    CSV-Datei nach `path`, in den database.COLUMN_NAMES-Spalten.
    Die ISBN ist bewusst NICHT enthalten - sie ist kein Teil des
    dauerhaften Datenmodells (sie gilt nur für den jeweils nächsten Band
    und wird ohnehin bei jedem Speichern verworfen, siehe isbn_lookup.py).
    Gibt die Anzahl der geschriebenen Zeilen zurück.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([db.LABELS[c] for c in db.COLUMN_NAMES])
        count = 0
        for entry in entries:
            writer.writerow([entry.get(c, "") or "" for c in db.COLUMN_NAMES])
            count += 1
    return count
