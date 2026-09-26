"""
sorting.py
Liefert je nach Spaltentyp einen passenden Sortierschlüssel, damit z.B. die
VÖ-Spalten wirklich chronologisch (nicht zeichenweise) sortiert werden.

Die VÖ-Spalten und "Zugang" enthalten überwiegend Datumsangaben
(TT.MM.JJJJ bzw. MM.JJJJ), daneben aber auch Freitext wie "TBA",
"Beendet", "JP16" oder "Band 17 11.06.2025". Erkannte Daten werden
chronologisch einsortiert, alles andere alphabetisch danach - so bleibt
die Sortierung auch bei gemischten Werten sinnvoll nutzbar.
"""

import re
from datetime import date

from database import VOE_COLUMNS

DATE_DMY_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")   # TT.MM.JJJJ
DATE_MY_RE = re.compile(r"^(\d{1,2})\.(\d{4})$")                # MM.JJJJ

DATE_COLUMNS = set(VOE_COLUMNS) | {"zugang"}
NUMERIC_COLUMNS = {"baende_bis", "gelesen_bis"}

# Gruppen-Reihenfolge innerhalb einer Spalte: erkannte Werte zuerst
# (nach ihrem tatsächlichen Wert sortiert), dann übriger Text, dann leer.
_GROUP_VALUE = 0
_GROUP_TEXT = 1
_GROUP_EMPTY = 2


def parse_date(value: str):
    """Öffentliche Variante von _parse_date - liefert ein echtes date-Objekt
    für erkannte TT.MM.JJJJ- oder MM.JJJJ-Werte, sonst None. Wird u.a. für
    den VÖ+1-Filter "Mit Datum" in der GUI verwendet."""
    return _parse_date((value or "").strip())


def _parse_date(value: str):
    m = DATE_DMY_RE.match(value)
    if m:
        day, month, year = (int(g) for g in m.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    m = DATE_MY_RE.match(value)
    if m:
        month, year = (int(g) for g in m.groups())
        try:
            return date(year, month, 1)
        except ValueError:
            return None

    return None


def sort_key(column: str, value: str):
    value = (value or "").strip()

    if not value:
        return (_GROUP_EMPTY, "")

    if column in DATE_COLUMNS:
        parsed = _parse_date(value)
        if parsed is not None:
            return (_GROUP_VALUE, parsed)
        return (_GROUP_TEXT, value.lower())

    if column in NUMERIC_COLUMNS:
        try:
            return (_GROUP_VALUE, float(value.replace(",", ".")))
        except ValueError:
            return (_GROUP_TEXT, value.lower())

    return (_GROUP_VALUE, value.lower())
