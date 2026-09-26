"""
tests/test_models.py
Tests für models.Werk: dataclass-Zugriff UND dict-kompatible Schnittstelle.
"""

import database as db
from models import Werk


def test_werk_has_all_database_columns_as_fields():
    werk = Werk()
    for col in db.COLUMN_NAMES:
        assert hasattr(werk, col)
    assert hasattr(werk, "id")


def test_werk_attribute_access():
    werk = Werk(titel="Testreihe", baende_bis="5")
    assert werk.titel == "Testreihe"
    assert werk.baende_bis == "5"
    assert werk.gelesen_bis == ""  # Standardwert


def test_werk_dict_style_access_matches_attribute_access():
    werk = Werk(titel="Testreihe")
    assert werk["titel"] == "Testreihe"
    assert werk.get("titel") == "Testreihe"
    assert werk.get("nicht_vorhanden", "default") == "default"


def test_werk_dict_style_assignment():
    werk = Werk(titel="Alt")
    werk["titel"] = "Neu"
    assert werk.titel == "Neu"


def test_werk_update_like_dict():
    werk = Werk(titel="Testreihe", baende_bis="5")
    werk.update({"baende_bis": "6", "unbekanntes_feld": "wird ignoriert"})
    assert werk.baende_bis == "6"
    assert not hasattr(werk, "unbekanntes_feld")


def test_werk_from_dict_ignores_unknown_keys():
    data = {"titel": "Testreihe", "baende_bis": "5", "isbn": "9783551123456"}
    werk = Werk.from_dict(data)
    assert werk.titel == "Testreihe"
    assert werk.baende_bis == "5"
    assert not hasattr(werk, "isbn")


def test_werk_to_dict_round_trip():
    original = dict.fromkeys(db.STORED_COLUMN_NAMES, "")
    original.update({"id": 42, "titel": "Testreihe", "verlag": "Carlsen Manga"})
    werk = Werk.from_dict(original)
    result = werk.to_dict()
    assert result == original


def test_werk_keeps_hidden_order_marks():
    werk = Werk.from_dict({"titel": "Sanda", "bestellt": "14", "angekommen": "13"})
    assert werk.to_dict()["bestellt"] == "14" and werk.to_dict()["angekommen"] == "13"


def test_werk_works_as_drop_in_for_logic_functions():
    # logic.increment_baende arbeitet nur ueber .get()/[] - muss also
    # genauso mit einem Werk wie mit einem echten Dict funktionieren.
    import logic

    werk = Werk(baende_bis="5", voe_1="TBA", voe_2="15.09.2026")
    result = logic.increment_baende(werk)
    assert result == 6
    assert werk.baende_bis == "6"
    assert werk.voe_1 == "15.09.2026"


def test_werk_contains():
    werk = Werk(titel="Testreihe")
    assert "titel" in werk
    assert "nicht_vorhanden" not in werk
