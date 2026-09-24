"""
tests/test_sorting.py
Tests für sorting.py: Datumserkennung (TT.MM.JJJJ / MM.JJJJ) und die
spaltenabhängigen Sortierschlüssel.
"""

from datetime import date

import sorting


# -------------------------------------------------------------------- parse_date

def test_parse_date_full_date():
    assert sorting.parse_date("15.09.2026") == date(2026, 9, 15)


def test_parse_date_month_year_only():
    assert sorting.parse_date("09.2026") == date(2026, 9, 1)


def test_parse_date_single_digit_day_and_month():
    assert sorting.parse_date("5.9.2026") == date(2026, 9, 5)


def test_parse_date_status_text_returns_none():
    for value in ("TBA", "Beendet", "Gestoppt", "NA", "Fortlaufend"):
        assert sorting.parse_date(value) is None


def test_parse_date_empty_or_none_returns_none():
    assert sorting.parse_date("") is None
    assert sorting.parse_date(None) is None


def test_parse_date_invalid_calendar_date_returns_none():
    assert sorting.parse_date("31.02.2026") is None  # 31. Februar existiert nicht


def test_parse_date_free_text_with_embedded_date_not_matched():
    # sort_key/parse_date erwarten das GESAMTE Feld als Datum, nicht nur
    # eine eingebettete Teilzeichenkette (z.B. "Band 17 11.06.2025")
    assert sorting.parse_date("Band 17 11.06.2025") is None


# ---------------------------------------------------------------------- sort_key

def test_sort_key_numeric_column_orders_numerically_not_alphabetically():
    # "10" muss NACH "2" kommen - bei reiner Zeichenkettensortierung wäre
    # es umgekehrt ("1" < "2")
    assert sorting.sort_key("baende_bis", "2") < sorting.sort_key("baende_bis", "10")


def test_sort_key_date_column_orders_chronologically():
    early = sorting.sort_key("voe_1", "01.01.2026")
    late = sorting.sort_key("voe_1", "01.01.2027")
    assert early < late


def test_sort_key_date_values_sort_before_text_values():
    date_key = sorting.sort_key("voe_1", "01.01.2026")
    text_key = sorting.sort_key("voe_1", "TBA")
    assert date_key < text_key


def test_sort_key_empty_sorts_last():
    text_key = sorting.sort_key("voe_1", "TBA")
    empty_key = sorting.sort_key("voe_1", "")
    assert text_key < empty_key


def test_sort_key_generic_column_alphabetic_case_insensitive():
    assert sorting.sort_key("verlag", "altraverse") == sorting.sort_key("verlag", "Altraverse")
    assert sorting.sort_key("verlag", "Altraverse") < sorting.sort_key("verlag", "Carlsen")
