"""
tests/test_csv_export.py
Tests für den CSV-Export und das Zusammenspiel mit dem Import: Semikolon
für Excel mit deutschen Einstellungen, Erkennung von Trennzeichen und
Zeichensatz beim Einlesen.
"""

import pytest

import config
import csv_export
import database as db
import import_csv


@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")


ENTRIES = [
    {"id": 1, "titel": "Sanda", "baende_bis": "12", "verlag": "Pegasus Manga", "kommentar": "Hinweis; mit Semikolon",
     "voe_1": "01.10.2026", "bestellt": "13"},
    {"id": 2, "titel": "Frieren - Nach dem Ende der Reise", "baende_bis": "14", "verlag": "Altraverse", "typ": "Manga"},
]


def test_export_uses_semicolon_and_utf8_bom(tmp_path):
    path = tmp_path / "export.csv"
    assert csv_export.export_csv(str(path), ENTRIES) == 2
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                            # BOM: Umlaute in Excel richtig
    header = raw.decode("utf-8-sig").splitlines()[0]
    assert header.split(";")[:2] == ["Titel", "Bände (bis)"]
    assert "bestellt" not in raw.decode("utf-8-sig")                 # interne Felder nicht im Export


def test_delimiter_is_configurable(tmp_path):
    config.set_value("csv_delimiter", ",")
    path = tmp_path / "export.csv"
    csv_export.export_csv(str(path), ENTRIES)
    assert path.read_text(encoding="utf-8-sig").splitlines()[0].startswith("Titel,Bände (bis)")


def test_export_can_be_imported_again(tmp_path):
    path = tmp_path / "export.csv"
    csv_export.export_csv(str(path), ENTRIES)
    entries, warnings = import_csv.parse_csv(str(path))
    assert warnings == []
    assert [e["titel"] for e in entries] == ["Sanda", "Frieren - Nach dem Ende der Reise"]
    assert entries[0]["kommentar"] == "Hinweis; mit Semikolon"       # Semikolon im Feld bleibt erhalten


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_import_detects_delimiter(tmp_path, delimiter):
    header = delimiter.join(db.LABELS[c] for c in db.COLUMN_NAMES)
    row = delimiter.join(["Sanda", "12"] + [""] * (len(db.COLUMN_NAMES) - 2))
    path = tmp_path / "liste.csv"
    path.write_text(header + "\n" + row + "\n", encoding="utf-8")
    entries, _ = import_csv.parse_csv(str(path))
    assert entries[0]["titel"] == "Sanda" and entries[0]["baende_bis"] == "12"


def test_import_falls_back_to_windows_1252(tmp_path):
    header = ";".join(db.LABELS[c] for c in db.COLUMN_NAMES)
    row = ";".join(["Die Tänzerin des Königs", "5"] + [""] * (len(db.COLUMN_NAMES) - 2))
    path = tmp_path / "excel_alt.csv"
    path.write_bytes((header + "\r\n" + row + "\r\n").encode("cp1252"))
    entries, _ = import_csv.parse_csv(str(path))
    assert entries[0]["titel"] == "Die Tänzerin des Königs"
