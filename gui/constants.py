"""
gui/constants.py
Konstanten und kleine reine Hilfsfunktionen, die von mehreren gui-Modulen
gemeinsam genutzt werden (Tabellen-Spaltenbreiten, Anzeige-Reihenfolge,
Filter-Optionen, VÖ-Hilfsfunktionen). Kein Qt-Widget-Code hier - reine
Daten und Funktionen.
"""

from typing import Optional

from PySide6.QtCore import Qt

import database as db
import sorting
from logic import parse_int

TYP_OPTIONEN = ["Manga", "Manhwa", "Light Novel"]
JA_NEIN_OPTIONEN = ["Ja", "Nein"]
APP_TITLE = "Manga & Light Novel Bibliothek"

# Spalten, die einen kleinen "+1"-Button zum schnellen Hochzählen bekommen
INCREMENTABLE_COLUMNS = ("baende_bis", "gelesen_bis")

# Anfangs-Spaltenbreiten (Pixel) - danach vom Nutzer per Ziehen am
# Spaltenrand frei änderbar (native Qt-Funktion des Tabellenkopfs).
COL_DEFAULT_WIDTHS = {
    "titel": 260,
    "baende_bis": 90,
    "komplett": 70,
    "beendet": 70,
    "gelesen_bis": 100,
    "typ": 85,
    "zugang": 65,
    "verlag": 140,
    "kommentar": 160,
    "voe_1": 110,
    "voe_2": 80,
    "voe_3": 80,
    "ruckstand": 90,
}

ROW_ID_ROLE = Qt.UserRole + 1
BAR_COLOR_ROLE = Qt.UserRole + 2  # Farbe des Balkens links in der Zelle (oder None)
PLUS_BTN_WIDTH = 30
PLUS_BTN_MARGIN = 4

# Feste Auswahl für den VÖ+1-Filter: bekannte Status-Werte + "Mit Datum"
# für alles, was ein tatsächlicher Termin (kein Status-Text) ist.
VOE1_FILTER_OPTIONS = ["Alle", "Beendet", "TBA", "Gestoppt", "NA", "Mit Datum"]
_VOE1_STATUS_KEYS = {"beendet", "tba", "gestoppt", "na"}


def _voe1_category(value):
    """Ordnet einen VÖ+1-Wert einer Filterkategorie zu: einem der bekannten
    Status-Texte, "datum" für eine echte erkannte Terminangabe, oder
    "text" für sonstigen Freitext (z.B. "Fortlaufend", "Band 17 ...")."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v in _VOE1_STATUS_KEYS:
        return v
    if sorting.parse_date(value):
        return "datum"
    return "text"


# Zusätzliche, rein berechnete (nicht in der Datenbank gespeicherte) Spalte:
# Rückstand = Bände (bis) - Gelesen bis. Erscheint nur in der Tabellenansicht
# und beim Sortieren, nicht im Bearbeiten-Formular, CSV-Export/-Import oder
# der Datenbank - wird bei jeder Anzeige live aus den beiden echten Feldern
# berechnet.
RUCKSTAND_COLUMN = "ruckstand"
DISPLAY_COLUMNS = list(db.COLUMN_NAMES) + [RUCKSTAND_COLUMN]
DISPLAY_LABELS = dict(db.LABELS)
DISPLAY_LABELS[RUCKSTAND_COLUMN] = "Rückstand"


def _ruckstand_value(entry) -> Optional[int]:
    """Bände (bis) minus Gelesen bis - je kleiner (bzw. negativer), desto
    aktueller ist der Nutzer mit dem Lesen. None, wenn eines der beiden
    Felder keine gültige Zahl enthält."""
    besitz = parse_int(entry.get("baende_bis"))
    gelesen = parse_int(entry.get("gelesen_bis"))
    if besitz is None or gelesen is None:
        return None
    return besitz - gelesen


# Für "Erscheinende Bücher" / "Ausstehend" in der Seitenleiste: alle drei
# VÖ-Spalten durchsuchen, nicht nur VÖ+1, da auch VÖ+2 und VÖ+3 bereits
# bekannte künftige Termine enthalten können.
VOE_COLUMNS = db.VOE_COLUMNS


def _entry_voe_dates(entry):
    """Liefert alle in den VÖ-Spalten eines Eintrags erkannten echten
    Termine (Status-Texte wie "TBA"/"Beendet" werden ignoriert) als Liste
    von (Spalten-Schlüssel, date)-Paaren."""
    found = []
    for col in VOE_COLUMNS:
        parsed = sorting.parse_date(entry.get(col))
        if parsed is not None:
            found.append((col, parsed))
    return found

