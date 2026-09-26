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
        "Verlag", "Kommentar", "VÖ +1", "VÖ +2", "VÖ +3",
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


def test_parse_csv_ignores_removed_voe_4_and_5_columns(tmp_path):
    # Ältere CSV-Dateien (14 Spalten, wie die ursprüngliche Liste) müssen
    # weiterhin importierbar sein - VÖ +4 / VÖ +5 werden verworfen.
    csv_file = tmp_path / "alt.csv"
    csv_file.write_text(
        ",bis,Komplett,Beendet,gelesen bis,Typ,Zugang,Verlag,Kommentar,VÖ +1,VÖ +2,VÖ +3,VÖ +4,VÖ +5\n"
        "Testtitel,7,Nein,Nein,3,Manga,08.2022,Altraverse,,TBA,KR 7,x,y,z\n",
        encoding="utf-8-sig",
    )
    entries, warnings = import_csv.parse_csv(str(csv_file))
    assert len(entries) == 1
    assert set(entries[0]) == set(db.COLUMN_NAMES)
    assert entries[0]["voe_3"] == "x"
    assert any("VÖ +4" in w for w in warnings)


def test_export_has_no_voe_4_and_5(tmp_path):
    import csv_export
    out = tmp_path / "out.csv"
    csv_export.export_csv(str(out), [{"titel": "T", "voe_1": "TBA"}])
    header = out.read_text(encoding="utf-8-sig").splitlines()[0]
    assert "VÖ +3" in header
    assert "VÖ +4" not in header and "VÖ +5" not in header
