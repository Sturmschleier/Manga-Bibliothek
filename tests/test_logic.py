"""
tests/test_logic.py
Tests für logic.py: die "+1"-Buttons-Logik (Bände (bis) und Gelesen bis).
Reine Funktionen ohne Datenbank-/GUI-Abhängigkeit.
"""

import logic


# --------------------------------------------------------------- increment_baende

def test_increment_baende_shifts_voe_columns_forward():
    entry = {"baende_bis": "5", "voe_1": "TBA", "voe_2": "15.09.2026", "voe_3": "", "voe_4": "", "voe_5": ""}
    result = logic.increment_baende(entry)
    assert result == 6
    assert entry["baende_bis"] == "6"
    assert entry["voe_1"] == "15.09.2026"  # rückt von VÖ+2 nach
    assert entry["voe_2"] == ""


def test_increment_baende_shifts_all_five_columns():
    entry = {
        "baende_bis": "1",
        "voe_1": "a", "voe_2": "b", "voe_3": "c", "voe_4": "d", "voe_5": "e",
    }
    logic.increment_baende(entry)
    assert (entry["voe_1"], entry["voe_2"], entry["voe_3"], entry["voe_4"], entry["voe_5"]) == (
        "b", "c", "d", "e", "",
    )


def test_increment_baende_sets_na_when_no_more_dates_left():
    entry = {"baende_bis": "1", "voe_1": "TBA", "voe_2": "", "voe_3": "", "voe_4": "", "voe_5": ""}
    logic.increment_baende(entry)
    assert entry["voe_1"] == "NA"


def test_increment_baende_fortlaufend_keeps_everything_unchanged():
    entry = {"baende_bis": "5", "voe_1": "Fortlaufend", "voe_2": "15.09.2026", "voe_3": "sollte bleiben"}
    result = logic.increment_baende(entry)
    assert result == 6
    assert entry["voe_1"] == "Fortlaufend"
    assert entry["voe_2"] == "15.09.2026"
    assert entry["voe_3"] == "sollte bleiben"


def test_increment_baende_fortlaufend_case_and_whitespace_insensitive():
    entry = {"baende_bis": "2", "voe_1": "  fortlaufend  ", "voe_2": "sollte bleiben"}
    logic.increment_baende(entry)
    assert entry["voe_2"] == "sollte bleiben"


def test_increment_baende_invalid_number_returns_none_and_leaves_entry_unchanged():
    entry = {"baende_bis": "abc", "voe_1": "TBA"}
    result = logic.increment_baende(entry)
    assert result is None
    assert entry["baende_bis"] == "abc"
    assert entry["voe_1"] == "TBA"


def test_increment_baende_empty_defaults_to_zero():
    entry = {"baende_bis": ""}
    result = logic.increment_baende(entry)
    assert result == 1


def test_increment_baende_clears_stale_isbn_field_if_present():
    # Falls "isbn" transient im Eintrag steckt (z.B. direkt nach einem
    # DB-Reload), muss increment_baende sie als ungültig leeren.
    entry = {"baende_bis": "5", "voe_1": "TBA", "isbn": "9783551123456"}
    logic.increment_baende(entry)
    assert entry["isbn"] == ""


# -------------------------------------------------------------- increment_gelesen

def test_increment_gelesen_normal_increase():
    entry = {"gelesen_bis": "3", "baende_bis": "5"}
    result = logic.increment_gelesen(entry)
    assert result == 4
    assert entry["gelesen_bis"] == "4"


def test_increment_gelesen_exceeds_baende_is_blocked():
    entry = {"gelesen_bis": "5", "baende_bis": "5"}
    result = logic.increment_gelesen(entry)
    assert result == logic.EXCEEDS
    assert entry["gelesen_bis"] == "5"  # unverändert, NICHT auf 6 erhöht


def test_increment_gelesen_equal_to_baende_is_reachable():
    # Gleichstand (gelesen == besitzt) ist erlaubt, nur DARÜBER wird blockiert
    entry = {"gelesen_bis": "4", "baende_bis": "5"}
    result = logic.increment_gelesen(entry)
    assert result == 5
    assert entry["gelesen_bis"] == "5"


def test_increment_gelesen_without_baende_value_skips_check():
    entry = {"gelesen_bis": "10", "baende_bis": ""}
    result = logic.increment_gelesen(entry)
    assert result == 11


def test_increment_gelesen_invalid_baende_skips_check():
    entry = {"gelesen_bis": "10", "baende_bis": "nicht-numerisch"}
    result = logic.increment_gelesen(entry)
    assert result == 11


def test_increment_gelesen_invalid_number_returns_none():
    entry = {"gelesen_bis": "xyz"}
    assert logic.increment_gelesen(entry) is None
