"""
tests/test_import_csv.py
Tests für die Kopfzeilen-Erkennung des CSV-Imports (import_csv._match_columns).
"""

import database as db
import import_csv


def test_match_columns_official_labels_in_order():
    header = [db.LABELS[c] for c in db.COLUMN_NAMES]
    assert import_csv._match_columns(header) == list(db.COLUMN_NAMES)


def test_match_columns_reordered_still_recognized():
    header = [db.LABELS[c] for c in db.COLUMN_NAMES]
    # Verlag und Kommentar vertauschen
    i, j = header.index("Verlag"), header.index("Kommentar")
    header[i], header[j] = header[j], header[i]

    mapping = import_csv._match_columns(header)
    assert mapping is not None
    assert mapping[i] == "kommentar"
    assert mapping[j] == "verlag"


def test_match_columns_original_informal_header():
    # Wie in der urspruenglichen "Manga - Besitz.csv": erste Spalte leer,
    # "bis" statt "Bände (bis)", ansonsten Original-Beschriftungen
    header = [
        "", "bis", "Komplett", "Beendet", "gelesen bis", "Typ", "Zugang",
        "Verlag", "Kommentar", "VÖ +1", "VÖ +2", "VÖ +3", "VÖ +4", "VÖ +5",
    ]
    mapping = import_csv._match_columns(header)
    assert mapping == list(db.COLUMN_NAMES)


def test_match_columns_unrecognized_header_returns_none():
    header = ["Name", "Preis", "Menge"] + ["?"] * (len(db.COLUMN_NAMES) - 3)
    assert import_csv._match_columns(header) is None


def test_match_columns_case_insensitive():
    header = [db.LABELS[c].upper() for c in db.COLUMN_NAMES]
    assert import_csv._match_columns(header) == list(db.COLUMN_NAMES)


def test_match_columns_duplicate_header_name_not_double_assigned():
    # Zwei Spalten mit demselben (erkannten) Namen duerfen nicht beide auf
    # dieselbe interne Spalte gemappt werden - das Ergebnis muss None sein,
    # da nicht alle Spalten dann noch eindeutig zuordenbar sind.
    header = [db.LABELS[c] for c in db.COLUMN_NAMES]
    header[1] = header[0]  # zweite Spalte auf "Titel" duplizieren
    assert import_csv._match_columns(header) is None
